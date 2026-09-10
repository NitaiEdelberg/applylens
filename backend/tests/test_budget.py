"""What a request drops when it runs out of budget, and what it never drops."""
import asyncio

import pytest

from src import budget as budget_mod
from src import trace as tr
from src.services import grounding as grounding_svc
from src.services import tailor as tailor_svc


@pytest.fixture
def model(monkeypatch):
    """Stub the model, and record which guardrail calls were made."""
    made = []

    async def fake(messages, temperature=0.2, schema=None):
        system = messages[0]["content"]
        if "resume writer" in system:
            made.append("tailor")
            return {"bullets": ["Wrote SQL against Snowflake."], "cover_letter": "Hi."}
        if "fact-checker" in system:
            made.append("ground_bullets")
            return {"checks": [{"statement": "Wrote SQL against Snowflake.",
                                "supported": True, "evidence": "SQL", "issue": None}]}
        if "extract, from a cover letter" in system:
            made.append("extract_claims")
            return {"claims": []}
        return {}

    monkeypatch.setattr(tailor_svc, "chat_json", fake)
    monkeypatch.setattr(grounding_svc, "chat_json", fake)
    return made


def _run(cv="Wrote SQL against Snowflake."):
    async def go():
        tr.start_trace("analyze")
        return await tailor_svc.tailor("A job", cv)
    return asyncio.run(go())


def test_within_budget_everything_runs(model):
    result = _run()
    assert result["degraded"] == []
    assert "ground_bullets" in model and "extract_claims" in model


def test_over_budget_the_cover_letter_check_is_skipped(model, monkeypatch):
    monkeypatch.setattr(budget_mod, "MAX_TOKENS", 1)  # already over on arrival
    monkeypatch.setattr(tailor_svc, "over_budget", budget_mod.over_budget)

    async def spend():
        # Tokens are counted per stage, so spend them inside one.
        tr.record_llm_call("m", {"prompt_tokens": 500, "completion_tokens": 500}, 10)

    async def go():
        tr.start_trace("analyze")
        await tr.traced("fit", spend)
        return await tailor_svc.tailor("A job", "Wrote SQL against Snowflake.")

    result = asyncio.run(go())
    assert [d["step"] for d in result["degraded"]] == ["cover_letter_grounding"]
    assert "tokens" in result["degraded"][0]["reason"]
    assert "extract_claims" not in model, "the cover-letter check is what gets dropped"


def test_the_bullet_guardrail_is_never_dropped(model, monkeypatch):
    monkeypatch.setattr(budget_mod, "MAX_SECONDS", 0.0)
    monkeypatch.setattr(tailor_svc, "over_budget", budget_mod.over_budget)
    result = _run()
    assert "ground_bullets" in model, "a result that stopped being fact-checked is worse than a slow one"
    assert result["grounding"], "the verdicts must still be there"


def test_a_degraded_run_says_so_rather_than_reporting_zero_flags(model, monkeypatch):
    monkeypatch.setattr(budget_mod, "MAX_SECONDS", 0.0)
    monkeypatch.setattr(tailor_svc, "over_budget", budget_mod.over_budget)
    result = _run()
    # cover_flagged_count is 0 because nothing was checked, so the degraded list
    # is the only thing that distinguishes "clean" from "not looked at".
    assert result["cover_flagged_count"] == 0
    assert result["degraded"]


def test_no_trace_means_no_budget_pressure():
    # /api/tailor called directly has no trace; it must not read as over budget.
    assert budget_mod.over_budget() is None
