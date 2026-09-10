"""Tracing has to survive the thing that makes it hard: concurrent stages.

extract, fit and tailor are gathered, so if the "current stage" were shared
state, a token count would land on whichever stage happened to be running.
"""
import asyncio
import json
import logging

from src import trace as tr


def test_a_trace_records_stages_in_order():
    async def run():
        t = tr.start_trace("analyze")

        async def work(_):
            return "done"

        await tr.traced("extract", work, 1)
        await tr.traced("fit", work, 2)
        return t.as_dict()

    out = asyncio.run(run())
    assert [s["name"] for s in out["stages"]] == ["extract", "fit"]
    assert out["request_id"] and len(out["request_id"]) == 12
    assert out["totals"]["llm_calls"] == 0


def test_model_calls_land_on_the_stage_that_made_them():
    async def run():
        t = tr.start_trace("analyze")

        async def slow_stage():
            await asyncio.sleep(0.01)
            tr.record_llm_call("model-a", {"prompt_tokens": 100, "completion_tokens": 10}, 5)

        async def fast_stage():
            tr.record_llm_call("model-b", {"prompt_tokens": 7, "completion_tokens": 3}, 1)

        await asyncio.gather(
            tr.traced("tailor", slow_stage),
            tr.traced("fit", fast_stage),
        )
        return t.as_dict()

    out = asyncio.run(run())
    by_name = {s["name"]: s for s in out["stages"]}
    assert [c["model"] for c in by_name["tailor"]["calls"]] == ["model-a"]
    assert [c["model"] for c in by_name["fit"]["calls"]] == ["model-b"]
    assert out["totals"]["prompt_tokens"] == 107
    assert out["totals"]["completion_tokens"] == 13
    assert out["totals"]["models"] == ["model-a", "model-b"]


def test_a_failing_stage_is_recorded_and_the_error_still_raises():
    async def run():
        t = tr.start_trace("analyze")

        async def boom():
            raise ValueError("nope")

        try:
            await tr.traced("fit", boom)
        except ValueError:
            pass
        return t.as_dict()

    out = asyncio.run(run())
    assert out["stages"][0]["error"] == "ValueError"


def test_cost_is_absent_until_real_prices_are_configured(monkeypatch):
    async def run():
        tr.start_trace("analyze")

        async def work():
            tr.record_llm_call("m", {"prompt_tokens": 1000, "completion_tokens": 1000}, 1)

        await tr.traced("fit", work)
        return tr.current_trace().as_dict()

    out = asyncio.run(run())
    assert "cost_usd" not in out["totals"], "a made-up price is worse than no price"

    monkeypatch.setattr(tr, "_PRICE_IN", "0.15")
    monkeypatch.setattr(tr, "_PRICE_OUT", "0.60")
    out = asyncio.run(run())
    assert out["totals"]["cost_usd"] == round((1000 * 0.15 + 1000 * 0.60) / 1_000_000, 6)


def test_events_are_json_lines_carrying_the_request_id(caplog):
    async def run():
        t = tr.start_trace("analyze")

        async def work():
            return None

        await tr.traced("fit", work)
        return t.request_id

    with caplog.at_level(logging.INFO, logger="applylens"):
        request_id = asyncio.run(run())

    events = [json.loads(r.message) for r in caplog.records if r.name == "applylens"]
    assert {e["event"] for e in events} >= {"request.start", "stage.ok"}
    assert all(e["request_id"] == request_id for e in events)
