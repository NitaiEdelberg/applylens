"""Repair agent: fixes the bullets the grounding guardrail flagged, with tools.

The analysis pipeline is fixed on purpose (extract, score, tailor, verify): an
LLM choosing the order of those steps would add cost and nothing else. Where a
decision genuinely helps is repair. A flagged bullet might be

  * true, but the evidence is in the career history rather than the CV,
  * an overstatement that a narrower rewrite can keep honestly,
  * or simply unsupported, in which case the honest move is to drop it.

Choosing between those needs looking things up first, so this is an agent: a
controller model picks one tool per step, sees the result, and decides again.

The harness, not the prompt, owns the rules that matter:

  * accept(text) is refused unless verify(text) passed on that exact text. The
    model cannot talk its way to a green bullet.
  * verify grounds against the CV plus only the career-history passages the
    agent actually retrieved, so evidence has to be found, not asserted.
  * Budgets: steps per bullet, steps per run, a wall-clock deadline, and the
    app's daily token budget. Running out leaves the bullet flagged, honestly.
  * The same tool call twice in a row is blocked and the model is told so,
    which breaks the commonest agent failure (looping on one action).
  * Every step is emitted as an event (tool, arguments, what came back, time),
    so the person watching sees the reasoning, not just the result.

The controller replies with structured JSON (thought, tool, args) under a
schema, not provider tool-calling: one of this app's outages was a tool-call
wrapper from constrained decoding, and JSON-with-schema already works on every
model in the fallback chain.
"""
import asyncio
import json
import os
import re
import time
from typing import Awaitable, Callable, Dict, List, Optional

from ..budget import over_budget
from ..llm import LLMError, chat_json, patience
from ..trace import traced
from .grounding import check_grounding
from .rag import _chunk, _retrieve, TfidfEmbeddings
from .untrusted import GUARD, as_data

TOOLS = ["search_cv", "search_career", "rewrite", "verify", "accept", "drop"]
MAX_STEPS_PER_BULLET = 7
MAX_STEPS_TOTAL = 24
DEADLINE_S = 120.0
# Decisions are short, so the controller asks the small model first. Groq
# meters each model's per-minute quota separately, which keeps the big model's
# budget for the rewrite and verify steps where quality matters. Measured: with
# the big model doing everything, a three-bullet run hit its per-minute limit.
CONTROLLER_MODELS = [m.strip() for m in os.getenv(
    "AGENT_CONTROLLER_MODELS", "openai/gpt-oss-20b,openai/gpt-oss-120b").split(",") if m.strip()]
RATE_LIMIT_PAUSE_S = 8.0
PATIENCE_S = float(os.getenv("AGENT_RATE_LIMIT_PATIENCE_S", "20"))

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string", "enum": TOOLS},
        "args": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "text": {"type": "string"},
                "reason": {"type": "string"},
                "use_evidence": {"type": "boolean"},
            },
        },
    },
    "required": ["thought", "tool", "args"],
}

CONTROLLER_SYSTEM = (
    "You repair one resume bullet that a fact-checker flagged as not supported by "
    "the candidate's CV. You work in steps: each reply picks ONE tool. Tools:\n"
    "- search_cv {query}: find CV lines about a skill, tool, employer or number.\n"
    "- search_career {query}: search the candidate's longer career history, if given.\n"
    "- rewrite {use_evidence}: write a new version of the bullet that avoids the "
    "flagged problem, using only facts found so far.\n"
    "- verify {text}: independent fact-check of a candidate bullet against the CV "
    "plus any career passages you retrieved.\n"
    "- accept {text}: keep a bullet. Only works if verify passed on that exact text.\n"
    "- drop {reason}: remove the bullet when nothing supports it.\n"
    "Prefer an honest, narrower bullet over dropping; prefer dropping over a "
    "claim you cannot verify. Never invent facts. Reply with JSON only: "
    '{"thought": "<one short sentence>", "tool": "<name>", "args": {...}}. ' + GUARD
)

_WORD = re.compile(r"[a-z0-9+#.]+")


def _tokens(s: str):
    return {w for w in _WORD.findall(s.lower()) if len(w) > 1}


def search_lines(text: str, query: str, k: int = 3) -> List[str]:
    """Deterministic keyword search over the CV's lines. No model, no network."""
    q = _tokens(query)
    if not q:
        return []
    lines = [l.strip(" -•\t") for l in re.split(r"[\n\r]+|(?<=[.;])\s+", text) if len(l.strip()) > 3]
    scored = sorted(((len(q & _tokens(l)) / len(q), l) for l in lines), key=lambda x: -x[0])
    return [l for s, l in scored[:k] if s > 0]


class Run:
    """Mutable state of one repair run, plus its budgets."""

    def __init__(self, jd_text: str, cv_text: str, career_text: str):
        self.jd_text = jd_text
        self.cv_text = cv_text
        self.career_chunks = _chunk(career_text) if career_text else []
        self.evidence: List[str] = []          # career passages the agent retrieved
        self.verified: Dict[str, dict] = {}    # candidate text -> grounding verdict
        self.accepted: List[str] = []          # bullets already kept in this run
        self.steps = 0
        self.started = time.monotonic()

    def grounding_source(self) -> str:
        return self.cv_text + ("\n\n" + "\n\n".join(self.evidence) if self.evidence else "")

    def out_of_time(self) -> bool:
        return time.monotonic() - self.started > DEADLINE_S


def salvage_decision(failed_generation):
    """Turn a rejected native tool call back into a decision.

    Shown a list of tools, gpt-oss sometimes answers with a native tool call,
    {"name": "search_cv", "arguments": {"query": "lead"}}, instead of the JSON
    asked for, and Groq rejects the whole reply (400 tool_use_failed). Measured
    on a live three-bullet run, that one quirk was the only reason a bullet went
    unresolved. The model said exactly what it wanted to do; this reads it.
    Only names in TOOLS are accepted, and the harness still checks every rule."""
    if not failed_generation:
        return None
    try:
        call = json.loads(failed_generation) if isinstance(failed_generation, str) else failed_generation
    except ValueError:
        return None
    if isinstance(call, dict) and "tool" in call and call.get("tool") in TOOLS:
        return {"thought": str(call.get("thought", "")), "tool": call["tool"], "args": call.get("args") or {}}
    name = call.get("name") if isinstance(call, dict) else None
    args = call.get("arguments") if isinstance(call, dict) else None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if name in TOOLS:
        return {"thought": "(read from the model's tool call)", "tool": name, "args": args or {}}
    return None


async def _default_decide(messages):
    try:
        return await chat_json(messages, temperature=0.1, schema=DECISION_SCHEMA, models=CONTROLLER_MODELS)
    except LLMError as exc:
        decision = salvage_decision(exc.failed_generation)
        if decision is None:
            raise
        return decision


async def _default_rewrite(run: Run, bullet: str, issue: str, use_evidence: bool) -> str:
    source = run.grounding_source() if use_evidence else run.cv_text
    if run.accepted:
        # Without this, two flagged bullets could both be "fixed" into the same
        # true fact (seen live: the Airflow migration, twice).
        issue = (issue + " Also do not repeat these bullets that are already used: "
                 + "; ".join(run.accepted))
    from .tailor import _generate_replacement  # local import: tailor imports grounding too
    return await _generate_replacement(run.jd_text, source, bullet, issue)


async def _default_verify(run: Run, text: str) -> dict:
    checks = await check_grounding(run.grounding_source(), [text])
    return checks[0] if checks else {"statement": text, "supported": False, "issue": "verifier returned nothing"}


class RepairAgent:
    def __init__(self, decide: Callable[[list], Awaitable[dict]] = None,
                 rewrite: Callable[..., Awaitable[str]] = None,
                 verify: Callable[..., Awaitable[dict]] = None,
                 max_steps_per_bullet: int = MAX_STEPS_PER_BULLET,
                 max_steps_total: int = MAX_STEPS_TOTAL):
        self.decide = decide or _default_decide
        self.rewrite = rewrite or _default_rewrite
        self.verify = verify or _default_verify
        self.max_per_bullet = max_steps_per_bullet
        self.max_total = max_steps_total

    async def run(self, jd_text: str, cv_text: str, flagged: List[dict], career_text: str = ""):
        """Async generator of events. `flagged` is [{"bullet", "issue"}]."""
        run = Run(jd_text, cv_text, career_text)
        # Free-tier Groq allows 8k tokens a minute per model and a three-bullet
        # repair needs about 25k, so this run waits out "try again in Ns"
        # instead of burning its retries on the next model (see llm.patience).
        patience(PATIENCE_S)
        yield {"type": "start", "bullets": len(flagged), "career_history": bool(run.career_chunks),
               "budget": {"steps_per_bullet": self.max_per_bullet, "steps_total": self.max_total,
                          "seconds": DEADLINE_S}}
        outcomes = []
        for index, item in enumerate(flagged):
            outcome = None
            async for event in self._repair_one(run, index, item.get("bullet", ""), item.get("issue") or ""):
                if event["type"] == "resolved":
                    outcome = event
                yield event
            outcomes.append(outcome)
        counts = {k: sum(1 for o in outcomes if o and o["outcome"] == k) for k in ("accepted", "dropped", "unresolved")}
        yield {"type": "done", "summary": dict(counts, steps=run.steps,
                                               ms=int((time.monotonic() - run.started) * 1000))}

    async def _repair_one(self, run: Run, index: int, bullet: str, issue: str):
        history: List[dict] = []
        last_call = None
        last_candidate = None
        for local_step in range(1, self.max_per_bullet + 1):
            stop = self._stop_reason(run)
            if stop:
                yield self._resolved(index, "unresolved", bullet, reason=stop)
                return
            messages = self._messages(run, bullet, issue, history, self.max_per_bullet - local_step + 1,
                                      last_candidate)
            t0 = time.monotonic()
            decision = None
            for attempt in (1, 2):
                try:
                    decision = await traced("agent.decide", self.decide, messages)
                    break
                except Exception as exc:  # rate limit, model down, bad JSON
                    # One pause and retry: a per-minute rate limit clears in
                    # seconds, and giving up on the bullet over it wastes the
                    # work already done. A second failure is final.
                    if attempt == 1 and not run.out_of_time():
                        yield {"type": "wait", "bullet": index, "seconds": RATE_LIMIT_PAUSE_S,
                               "reason": f"controller call failed ({type(exc).__name__}); pausing once"}
                        await asyncio.sleep(RATE_LIMIT_PAUSE_S)
                        continue
                    yield self._resolved(index, "unresolved", bullet,
                                         reason=f"controller failed: {type(exc).__name__}")
                    return
            tool = decision.get("tool")
            args = decision.get("args") or {}
            thought = str(decision.get("thought", ""))[:240]
            run.steps += 1

            call = (tool, json.dumps(args, sort_keys=True))
            if tool not in TOOLS:
                observation, ok = f"unknown tool {tool!r}; use one of {TOOLS}", False
            elif call == last_call:
                hint = ""
                if last_candidate and last_candidate not in run.verified:
                    hint = " There is an unverified candidate: call verify on it."
                elif last_candidate and run.verified.get(last_candidate, {}).get("supported"):
                    hint = " The candidate passed verify: call accept on it."
                observation, ok = "blocked: you just made this exact call." + (hint or " Try something different."), False
            else:
                try:
                    observation, ok, final = await traced(
                        "agent." + tool, self._execute, run, tool, args, bullet, issue, last_candidate)
                except Exception as exc:  # a tool failure is an observation, not a crash
                    observation, ok, final = f"tool error: {type(exc).__name__}", False, None
                if tool == "rewrite" and ok:
                    last_candidate = observation
                if final is not None:
                    final["bullet"] = index  # _execute does not know which bullet this is
                    yield self._step(index, local_step, tool, args, thought, observation, ok, t0)
                    yield final
                    return
            last_call = call
            history.append({"tool": tool, "args": args, "observation": observation, "ok": ok})
            yield self._step(index, local_step, tool, args, thought, observation, ok, t0)
        yield self._resolved(index, "unresolved", bullet, reason="step budget for this bullet used up")

    async def _execute(self, run: Run, tool: str, args: dict, bullet: str, issue: str, last_candidate):
        """Returns (observation, ok, resolved_event_or_None)."""
        if tool == "search_cv":
            hits = search_lines(run.cv_text, args.get("query", ""))
            return (hits or "no CV line matches that"), bool(hits), None
        if tool == "search_career":
            if not run.career_chunks:
                return "no career history was provided", False, None
            query = args.get("query", "") or bullet
            # TF-IDF gives an all-zero vector for a query whose words appear
            # nowhere in the history, and the similarity step then raises. That
            # surfaced as "tool error" and the agent kept searching instead of
            # concluding there is no evidence. No shared word means no evidence.
            if not _tokens(query) & set().union(*(_tokens(c) for c in run.career_chunks)):
                return "nothing relevant in the career history", False, None
            loop = asyncio.get_running_loop()
            hits = await loop.run_in_executor(
                None, _retrieve, run.career_chunks, TfidfEmbeddings().fit(run.career_chunks), query, 2)
            new = [h for h in hits if h not in run.evidence]
            run.evidence.extend(new)
            return (hits or "nothing relevant in the career history"), bool(hits), None
        if tool == "rewrite":
            text = await self.rewrite(run, bullet, issue, bool(args.get("use_evidence", True)))
            return (text or "rewrite produced nothing"), bool(text), None
        if tool == "verify":
            text = (args.get("text") or last_candidate or "").strip()
            if not text:
                return "nothing to verify: rewrite first or pass text", False, None
            verdict = await self.verify(run, text)
            run.verified[text] = verdict
            if verdict.get("supported"):
                return {"supported": True, "evidence": verdict.get("evidence")}, True, None
            return {"supported": False, "issue": verdict.get("issue")}, False, None
        if tool == "accept":
            text = (args.get("text") or last_candidate or "").strip()
            verdict = run.verified.get(text)
            if not verdict or not verdict.get("supported"):
                # The rule that makes this safe lives here, not in the prompt.
                return "refused: accept only works on text that passed verify", False, None
            run.accepted.append(text)
            return "accepted", True, self._resolved(None, "accepted", text,
                                                     evidence=verdict.get("evidence"), original=bullet)
        if tool == "drop":
            reason = (args.get("reason") or "no supporting evidence").strip()[:200]
            return "dropped", True, self._resolved(None, "dropped", bullet, reason=reason)
        return f"unknown tool {tool!r}", False, None

    def _stop_reason(self, run: Run) -> Optional[str]:
        if run.steps >= self.max_total:
            return "step budget for the run used up"
        if run.out_of_time():
            return "time budget used up"
        if over_budget():
            return "daily token budget reached"
        return None

    def _messages(self, run: Run, bullet: str, issue: str, history: List[dict], steps_left: int,
                  candidate: Optional[str] = None):
        log = "\n".join(
            f"{i + 1}. {h['tool']} {json.dumps(h['args'], ensure_ascii=False)} -> "
            f"{json.dumps(h['observation'], ensure_ascii=False)[:200]}"
            for i, h in enumerate(history)) or "(nothing yet)"
        user = (
            # The controller only needs the gist of the job: it picks tools, it
            # does not write. Sending 3k characters every step pushed a run past
            # Groq's per-minute token limit; rewrite and verify still get it whole.
            f"JOB (start):\n{as_data('JOB', run.jd_text[:800])}\n\n"
            f"FLAGGED BULLET:\n{as_data('BULLET', bullet)}\n"
            f"WHY IT WAS FLAGGED: {issue or 'not supported by the CV'}\n"
            f"CAREER HISTORY AVAILABLE: {'yes' if run.career_chunks else 'no'}\n\n"
            f"STEPS SO FAR:\n{log}\n\n{self._candidate_line(run, candidate)}"
            f"Steps left for this bullet: {steps_left}. Pick the next tool."
        )
        return [{"role": "system", "content": CONTROLLER_SYSTEM}, {"role": "user", "content": user}]

    @staticmethod
    def _candidate_line(run: Run, candidate: Optional[str]) -> str:
        # The step log alone was not enough for the small controller model: in a
        # live run it rewrote, then chose rewrite again four times instead of
        # verifying. Spelling out where the candidate stands fixed that.
        if not candidate:
            return "CURRENT CANDIDATE: none yet.\n"
        verdict = run.verified.get(candidate)
        if verdict is None:
            state = "NOT VERIFIED YET (next: verify it)"
        elif verdict.get("supported"):
            state = "PASSED verify (next: accept it)"
        else:
            state = f"FAILED verify: {verdict.get('issue')} (next: rewrite more narrowly, or drop)"
        return f"CURRENT CANDIDATE: {json.dumps(candidate, ensure_ascii=False)} -> {state}\n"

    @staticmethod
    def _step(index, n, tool, args, thought, observation, ok, t0):
        return {"type": "step", "bullet": index, "n": n, "tool": tool, "args": args, "thought": thought,
                "observation": observation, "ok": ok, "ms": int((time.monotonic() - t0) * 1000)}

    @staticmethod
    def _resolved(index, outcome, bullet, **extra):
        return dict({"type": "resolved", "bullet": index, "outcome": outcome, "text": bullet}, **extra)

