"""The repair agent's harness: the rules hold no matter what the controller says.

The controller is scripted here (a list of decisions), so every test is about
the harness, not about a model's mood: accept needs a passing verify on that
exact text, repeats are blocked, budgets stop the run, evidence has to be
retrieved, and every failure leaves the bullet honestly unresolved.
"""
import asyncio

import pytest

from src.services import agent as agent_mod
from src.services.agent import RepairAgent, search_lines

CV = ("Built a rehearsal web app with Node.js, Express, PostgreSQL and Socket.io.\n"
      "Deployed a FastAPI prompt-injection detector using scikit-learn.\n"
      "QA / Solutions Engineer writing heavy SQL on Snowflake and BigQuery.")
CAREER = ("Led the migration of nightly ETL jobs to Airflow at Jigso.\n\n"
          "Mentored two junior analysts on SQL performance tuning.")
JD = "Data engineer. Airflow, SQL, Python."


def scripted(*decisions):
    queue = list(decisions)

    async def decide(messages):
        decide.seen.append(messages[-1]["content"])
        if not queue:
            raise RuntimeError("script ran out")
        d = queue.pop(0)
        if isinstance(d, Exception):
            raise d
        return d
    decide.seen = []
    return decide


def step(tool, thought="", **args):
    return {"thought": thought, "tool": tool, "args": args}


async def fake_rewrite(run, bullet, issue, use_evidence):
    return "Migrated nightly ETL jobs to Airflow" if use_evidence and run.evidence else "Wrote SQL on Snowflake"


def verifier(supported_texts):
    async def verify(run, text):
        verify.calls.append((text, run.grounding_source()))
        ok = text in supported_texts
        return {"statement": text, "supported": ok, "evidence": "line" if ok else None,
                "issue": None if ok else "not in the CV"}
    verify.calls = []
    return verify


def collect(agent, flagged, career=""):
    async def go():
        return [e async for e in agent.run(JD, CV, flagged, career_text=career)]
    return asyncio.run(go())


def resolved(events):
    return [e for e in events if e["type"] == "resolved"]


@pytest.fixture(autouse=True)
def plenty_of_budget(monkeypatch):
    monkeypatch.setattr(agent_mod, "over_budget", lambda: False)


def test_finds_evidence_in_career_history_rewrites_verifies_and_accepts():
    verify = verifier({"Migrated nightly ETL jobs to Airflow"})
    agent = RepairAgent(
        decide=scripted(step("search_cv", query="Airflow"),
                        step("search_career", query="Airflow ETL"),
                        step("rewrite", use_evidence=True),
                        step("verify", text="Migrated nightly ETL jobs to Airflow"),
                        step("accept", text="Migrated nightly ETL jobs to Airflow")),
        rewrite=fake_rewrite, verify=verify)
    events = collect(agent, [{"bullet": "Led Airflow platform team of 10", "issue": "no Airflow in CV"}], CAREER)
    r = resolved(events)[0]
    assert r["outcome"] == "accepted" and r["text"] == "Migrated nightly ETL jobs to Airflow"
    assert r["original"] == "Led Airflow platform team of 10"
    # verify grounded against CV + the passage the agent actually retrieved
    assert "Airflow at Jigso" in verify.calls[0][1]
    assert events[-1]["summary"]["accepted"] == 1


def test_accept_without_a_passing_verify_is_refused():
    agent = RepairAgent(
        decide=scripted(step("accept", text="Invented a new database"),
                        step("drop", reason="nothing supports it")),
        verify=verifier(set()))
    events = collect(agent, [{"bullet": "Invented a new database", "issue": "not in CV"}])
    first = [e for e in events if e["type"] == "step"][0]
    assert first["tool"] == "accept" and first["ok"] is False and "refused" in first["observation"]
    assert resolved(events)[0]["outcome"] == "dropped"


def test_accept_after_a_failed_verify_is_still_refused():
    agent = RepairAgent(
        decide=scripted(step("verify", text="Led a team of 8"),
                        step("accept", text="Led a team of 8"),
                        step("drop", reason="unsupported")),
        verify=verifier(set()))
    events = collect(agent, [{"bullet": "Led a team of 8", "issue": "x"}])
    assert [e["ok"] for e in events if e["type"] == "step"] == [False, False, True]
    assert resolved(events)[0]["outcome"] == "dropped"


def test_verify_only_counts_for_the_exact_text_that_passed():
    agent = RepairAgent(
        decide=scripted(step("verify", text="Wrote SQL on Snowflake"),
                        step("accept", text="Wrote SQL on Snowflake and led the data team"),
                        step("drop", reason="x")),
        verify=verifier({"Wrote SQL on Snowflake"}))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert resolved(events)[0]["outcome"] == "dropped"


def test_repeating_the_same_call_is_blocked():
    agent = RepairAgent(
        decide=scripted(step("search_cv", query="Kubernetes"),
                        step("search_cv", query="Kubernetes"),
                        step("drop", reason="no Kubernetes anywhere")),
        verify=verifier(set()))
    events = collect(agent, [{"bullet": "Ran Kubernetes clusters", "issue": "i"}])
    second = [e for e in events if e["type"] == "step"][1]
    assert "blocked" in second["observation"]


def test_step_budget_leaves_the_bullet_unresolved_not_accepted():
    loop = [step("search_cv", query=f"q{i}") for i in range(20)]
    agent = RepairAgent(decide=scripted(*loop), verify=verifier(set()), max_steps_per_bullet=3)
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    r = resolved(events)[0]
    assert r["outcome"] == "unresolved" and "budget" in r["reason"]
    assert len([e for e in events if e["type"] == "step"]) == 3


def test_run_wide_budget_spans_bullets():
    agent = RepairAgent(decide=scripted(*[step("search_cv", query=f"q{i}") for i in range(20)]),
                        verify=verifier(set()), max_steps_per_bullet=5, max_steps_total=6)
    events = collect(agent, [{"bullet": "a", "issue": "i"}, {"bullet": "b", "issue": "i"}])
    outcomes = [r["reason"] for r in resolved(events)]
    assert "run used up" in outcomes[1]
    assert events[-1]["summary"]["steps"] == 6


def test_daily_token_budget_stops_before_spending(monkeypatch):
    monkeypatch.setattr(agent_mod, "over_budget", lambda: True)
    decide = scripted(step("drop", reason="x"))
    events = collect(RepairAgent(decide=decide, verify=verifier(set())), [{"bullet": "b", "issue": "i"}])
    assert resolved(events)[0]["reason"] == "daily token budget reached"
    assert decide.seen == []


def test_controller_failure_is_unresolved_not_a_crash(monkeypatch):
    monkeypatch.setattr(agent_mod, "RATE_LIMIT_PAUSE_S", 0)
    agent = RepairAgent(decide=scripted(RuntimeError("model gone"), RuntimeError("still gone")),
                        verify=verifier(set()))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert resolved(events)[0]["outcome"] == "unresolved"
    assert events[-1]["type"] == "done"


def test_unknown_tool_is_reported_back_to_the_controller():
    decide = scripted({"thought": "", "tool": "delete_cv", "args": {}}, step("drop", reason="x"))
    events = collect(RepairAgent(decide=decide, verify=verifier(set())), [{"bullet": "b", "issue": "i"}])
    assert "unknown tool" in [e for e in events if e["type"] == "step"][0]["observation"]
    assert "unknown tool" in decide.seen[1], "the controller must see its own mistake"


def test_search_career_without_history_says_so():
    events = collect(RepairAgent(decide=scripted(step("search_career", query="x"), step("drop", reason="x")),
                                 verify=verifier(set())), [{"bullet": "b", "issue": "i"}])
    assert "no career history" in [e for e in events if e["type"] == "step"][0]["observation"]


def test_search_lines_is_deterministic_keyword_search():
    assert search_lines(CV, "Snowflake SQL")[0].startswith("QA / Solutions Engineer")
    assert search_lines(CV, "Kubernetes") == []


def test_event_stream_shape():
    agent = RepairAgent(decide=scripted(step("drop", reason="x")), verify=verifier(set()))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert [e["type"] for e in events] == ["start", "step", "resolved", "done"]
    assert set(events[1]) >= {"bullet", "n", "tool", "args", "thought", "observation", "ok", "ms"}


# ---- the streaming endpoint ----

def test_endpoint_streams_events_and_restores_personal_details(monkeypatch):
    from fastapi.testclient import TestClient
    from src import server

    seen_cv = []

    class Fake(RepairAgent):
        def __init__(self):
            async def decide(messages):
                return step("drop", reason="no evidence")
            super().__init__(decide=decide, verify=verifier(set()))

        async def run(self, jd_text, cv_text, flagged, career_text=""):
            seen_cv.append(cv_text)
            async for e in super().run(jd_text, cv_text, flagged, career_text):
                yield e
    monkeypatch.setattr(server, "RepairAgent", Fake)

    client = TestClient(server.app)
    cv = CV + "\nContact: nitai.test@example.com"
    r = client.post("/api/agent/repair", json={"jd_text": JD, "cv_text": cv,
                                                "flagged": [{"bullet": "Led Airflow team", "issue": "x"}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    import json as _json
    events = [_json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "step", "resolved", "done"]
    assert "nitai.test@example.com" not in seen_cv[0], "the model must not see the email"


def test_endpoint_caps_how_many_bullets_one_run_may_repair():
    from fastapi.testclient import TestClient
    from src import server
    r = TestClient(server.app).post("/api/agent/repair", json={
        "jd_text": JD, "cv_text": CV, "flagged": [{"bullet": f"b{i}"} for i in range(7)]})
    assert r.status_code == 422


def test_search_career_with_no_shared_word_is_no_evidence_not_an_error():
    events = collect(RepairAgent(decide=scripted(step("search_career", query="dbt"), step("drop", reason="x")),
                                 verify=verifier(set())), [{"bullet": "b", "issue": "i"}], CAREER)
    first = [e for e in events if e["type"] == "step"][0]
    assert first["observation"] == "nothing relevant in the career history"


def test_a_rate_limited_controller_pauses_once_then_continues(monkeypatch):
    monkeypatch.setattr(agent_mod, "RATE_LIMIT_PAUSE_S", 0)
    agent = RepairAgent(decide=scripted(RuntimeError("429"), step("drop", reason="x")), verify=verifier(set()))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert [e["type"] for e in events] == ["start", "wait", "step", "resolved", "done"]
    assert resolved(events)[0]["outcome"] == "dropped"


def test_two_controller_failures_in_a_row_are_final(monkeypatch):
    monkeypatch.setattr(agent_mod, "RATE_LIMIT_PAUSE_S", 0)
    agent = RepairAgent(decide=scripted(RuntimeError("429"), RuntimeError("429")), verify=verifier(set()))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert resolved(events)[0]["outcome"] == "unresolved"


def test_a_rejected_native_tool_call_is_salvaged_as_the_decision():
    from src.services.agent import salvage_decision
    assert salvage_decision('{"name": "search_cv", "arguments": {"query":"lead"}}') == {
        "thought": "(read from the model's tool call)", "tool": "search_cv", "args": {"query": "lead"}}
    assert salvage_decision('{"name": "search_cv", "arguments": "{\\"query\\": \\"x\\"}"}')["args"] == {"query": "x"}
    assert salvage_decision('{"name": "rm_rf", "arguments": {}}') is None   # not one of ours
    assert salvage_decision("not json") is None
    assert salvage_decision(None) is None


def test_default_decide_uses_the_salvage(monkeypatch):
    from src.llm import LLMError

    async def rejected(*a, **kw):
        e = LLMError("Groq API 400: tool_use_failed")
        e.failed_generation = '{"name": "drop", "arguments": {"reason": "nothing supports it"}}'
        raise e
    monkeypatch.setattr(agent_mod, "chat_json", rejected)
    d = asyncio.run(agent_mod._default_decide([]))
    assert d["tool"] == "drop" and d["args"]["reason"] == "nothing supports it"


def test_the_controller_is_told_where_the_candidate_stands():
    decide = scripted(step("rewrite", use_evidence=False), step("rewrite", use_evidence=False),
                      step("verify"), step("accept"))
    agent = RepairAgent(decide=decide, rewrite=fake_rewrite, verify=verifier({"Wrote SQL on Snowflake"}))
    events = collect(agent, [{"bullet": "b", "issue": "i"}])
    assert "CURRENT CANDIDATE: none yet" in decide.seen[0]
    assert "NOT VERIFIED YET" in decide.seen[1]
    blocked = [e for e in events if e["type"] == "step"][1]
    assert "call verify on it" in blocked["observation"]
    assert "PASSED verify" in decide.seen[3]
    assert resolved(events)[0]["outcome"] == "accepted"


def test_rewrites_are_told_which_bullets_are_already_used(monkeypatch):
    seen = []

    async def gen(jd, source, bullet, issue):
        seen.append(issue)
        return "Wrote SQL on Snowflake"
    monkeypatch.setattr("src.services.tailor._generate_replacement", gen)
    run = agent_mod.Run(JD, CV, "")
    run.accepted.append("Migrated ETL jobs to Airflow")
    asyncio.run(agent_mod._default_rewrite(run, "b", "not in CV", False))
    assert "Migrated ETL jobs to Airflow" in seen[0]


def test_trace_counts_answered_calls_separately_from_rejected_ones():
    from src.trace import Stage, Trace
    t = Trace("x")
    st = Stage("s")
    st.calls = [{"model": "m", "status": 200, "prompt_tokens": 5}, {"model": "m", "status": 429},
                {"model": "m", "status": 400}]
    t.add(st)
    totals = t.as_dict()["totals"]
    assert (totals["llm_calls"], totals["failed_calls"], totals["rate_limited"]) == (1, 2, 1)
