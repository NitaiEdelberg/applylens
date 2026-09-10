"""Generate CV-grounded resume bullets + a cover letter, then verify grounding."""
import asyncio

from ..budget import over_budget
from ..llm import chat_json
from ..trace import log_event
from ..prompts import render
from .untrusted import GUARD, as_data
from .grounding import check_grounding, check_cover_letter

# The tailoring prompt lives in backend/prompts/tailor/*.txt so a change to it
# is a diff and an A/B run, not an untracked edit. Set PROMPT_TAILOR_VERSION to
# pick one; evals/run_prompt_ab.py scores them against each other.
TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {"type": "array", "items": {"type": "string"}},
        "cover_letter": {"type": "string"},
    },
    "required": ["bullets", "cover_letter"],
}

REGEN_SCHEMA = {
    "type": "object",
    "properties": {"bullet": {"type": "string"}},
    "required": ["bullet"],
}


async def tailor(jd_text: str, cv_text: str, version: str = None) -> dict:
    system, prompt = render(
        "tailor", version,
        guard=GUARD,
        job=as_data("JOB", jd_text),
        cv=as_data("CV", cv_text),
    )
    data = await chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=0.4,
        schema=TAILOR_SCHEMA,
    )
    bullets = data.get("bullets", []) or []
    cover_letter = data.get("cover_letter", "")

    # Guardrail: fact-check every generated bullet AND the cover letter's
    # factual self-claims against the CV — concurrently.
    #
    # Unless the request has run out of budget, in which case the bullets are
    # still checked (that is the guardrail) and the cover letter's claims are
    # not (it is a draft to edit). The result says so instead of quietly
    # returning an unchecked letter.
    exhausted = over_budget()
    if exhausted:
        log_event("budget.degraded", step="cover_letter_grounding", reason=exhausted)
        grounding = await check_grounding(cv_text, bullets)
        cover = {"claims": [], "flagged_count": 0}
    else:
        grounding, cover = await asyncio.gather(
            check_grounding(cv_text, bullets),
            check_cover_letter(cv_text, cover_letter),
        )
    flagged = [g for g in grounding if not g["supported"]]

    return {
        "bullets": bullets,
        "cover_letter": cover_letter,
        "grounding": grounding,
        "flagged_count": len(flagged),
        "cover_grounding": cover["claims"],
        "cover_flagged_count": cover["flagged_count"],
        "degraded": ([{"step": "cover_letter_grounding", "reason": exhausted}]
                     if exhausted else []),
    }


# Bounded self-correction: 1 initial regeneration + at most 1 retry.
_MAX_ATTEMPTS = 2

_REGEN_SYSTEM = (
    "You rewrite a single resume bullet so it is tailored to a target job while "
    "using ONLY facts present in the candidate's CV. A prior version of this "
    "bullet was flagged by a fact-checker for making a claim the CV does not "
    "support. Rewrite it to keep the JD relevance but drop or replace the "
    "unsupported claim with something the CV actually backs. Never invent skills, "
    "tools, employers, titles, or metrics. Respond with JSON only. " + GUARD
)


async def _generate_replacement(jd_text: str, cv_text: str, bullet: str, issue: str) -> str:
    """Ask the model for ONE replacement bullet, conditioned on the failure reason."""
    issue_line = (
        f'The previous bullet was flagged for this specific problem:\n"""{issue}"""\n'
        "You MUST avoid that problem in your rewrite."
        if issue and issue.strip()
        else "The previous bullet was flagged as not supported by the CV. "
        "Rewrite it using only claims the CV clearly backs."
    )
    prompt = f"""Rewrite ONE resume bullet.

{issue_line}

Rules:
- Stay tailored to the JOB below (impact-oriented, start with a verb).
- Use ONLY facts present in the CV. Do not claim any skill, tool, employer,
  title, or number that is not in the CV.
- Return exactly one replacement bullet.

JOB:
{as_data("JOB", jd_text)}

CV:
{as_data("CV", cv_text)}

PREVIOUS (flagged) BULLET:
{as_data("BULLET", bullet)}

Return JSON: {{"bullet": str}}"""
    data = await chat_json(
        [
            {"role": "system", "content": _REGEN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        schema=REGEN_SCHEMA,
    )
    return (data.get("bullet") or "").strip()


async def regenerate_bullet(jd_text: str, cv_text: str, bullet: str, issue: str) -> dict:
    """Closed detection -> repair -> re-verification loop for a single bullet.

    Regenerates the bullet conditioned on the flagged `issue`, then INDEPENDENTLY
    re-checks the new bullet with check_grounding (never trusting the generation
    step). If still unsupported, retries once more; after the bound, returns the
    best attempt with its honest verdict — never fabricating a green.
    """
    current_issue = issue or ""
    best = None
    for _ in range(_MAX_ATTEMPTS):
        new_bullet = await _generate_replacement(jd_text, cv_text, bullet, current_issue)
        checks = await check_grounding(cv_text, [new_bullet])
        grounding = checks[0] if checks else {
            "statement": new_bullet,
            "supported": False,
            "evidence": None,
            "issue": "Could not verify the regenerated bullet.",
        }
        best = {"bullet": new_bullet, "grounding": grounding}
        if grounding.get("supported"):
            return best
        # Feed the fresh failure reason back into the next attempt.
        current_issue = grounding.get("issue") or current_issue
    return best
