"""How the model client behaves when the upstream misbehaves.

Four upstream failures, four different right answers: a retired model means try
another model, a rate limit means try the same one again later, an unsupported
response schema means ask for less, and a sustained outage means stop asking.

Sync tests driving asyncio.run, so this needs no pytest-asyncio plugin.
"""
import asyncio
import json

import httpx
import pytest

from src import llm
from src.resilience import CircuitBreaker, CircuitOpen


def _fake_groq(handler):
    """An httpx.AsyncClient stand-in wired to a fake Groq endpoint."""
    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return _Client


def _ok(usage=None):
    body = {"choices": [{"message": {"content": '{"ok": true}'}}]}
    if usage:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _retired():
    return httpx.Response(404, json={"error": {
        "message": "The model `x` does not exist or you do not have access to it.",
        "code": "model_not_found"}})


@pytest.fixture(autouse=True)
def fresh_client(monkeypatch):
    """Module state is process-wide; every test starts from a clean one."""
    monkeypatch.setattr(llm, "_working_model", None)
    monkeypatch.setattr(llm, "_schema_supported", True)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GROQ_MODEL", "dead-model")
    monkeypatch.setattr(llm, "BACKOFF_BASE", 0.0)  # no real sleeping in tests
    monkeypatch.setattr(llm, "_breaker", CircuitBreaker(failure_threshold=4))


@pytest.fixture
def groq(monkeypatch):
    """Records the model ids tried; every id but openai/gpt-oss-120b is retired."""
    tried = []

    def handler(request):
        model = json.loads(request.content)["model"]
        tried.append(model)
        return _ok() if model == "openai/gpt-oss-120b" else _retired()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))
    return tried


def test_falls_through_a_retired_model(groq):
    out = asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert out == '{"ok": true}'
    assert groq == ["dead-model", "openai/gpt-oss-120b"]


def test_working_model_is_remembered(groq):
    asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    asyncio.run(llm.chat([{"role": "user", "content": "again"}]))
    # The second call skips the dead id instead of paying for the 404 again.
    assert groq == ["dead-model", "openai/gpt-oss-120b", "openai/gpt-oss-120b"]


def test_a_rate_limit_retries_the_same_model(monkeypatch):
    tried = []

    def handler(request):
        tried.append(json.loads(request.content)["model"])
        # Busy twice, then fine: the point is that it is the SAME model.
        return _ok() if len(tried) > 2 else httpx.Response(429, json={"error": "slow down"})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    assert asyncio.run(llm.chat([{"role": "user", "content": "hi"}])) == '{"ok": true}'
    assert tried == ["openai/gpt-oss-120b"] * 3


def test_a_rate_limit_falls_through_to_another_model_after_the_bound(monkeypatch):
    # Groq meters each model separately, so once the retries on one are spent,
    # the next model in the chain is a real mitigation rather than a repeat.
    tried = []

    def handler(request):
        tried.append(json.loads(request.content)["model"])
        return httpx.Response(429, json={"error": "slow down"})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    with pytest.raises(llm.LLMError) as exc:
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert "429" in str(exc.value)
    assert tried == ["openai/gpt-oss-120b"] * llm.MAX_ATTEMPTS \
        + ["openai/gpt-oss-20b"] * llm.MAX_ATTEMPTS


def test_an_unsupported_schema_degrades_to_json_mode(monkeypatch):
    formats = []

    def handler(request):
        body = json.loads(request.content)
        fmt = (body.get("response_format") or {}).get("type")
        formats.append(fmt)
        if fmt == "json_schema":
            return httpx.Response(400, json={"error": {
                "message": "response_format json_schema is not supported for this model"}})
        return _ok()

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert asyncio.run(llm.chat([{"role": "user", "content": "hi"}], schema=schema))
    assert formats == ["json_schema", "json_object"]
    # And it stops asking for the rest of the process.
    assert llm._schema_supported is False


def test_an_auth_error_is_not_retried(monkeypatch):
    tried = []

    def handler(request):
        tried.append(1)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    with pytest.raises(llm.LLMError):
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert len(tried) == 1, "a bad key will still be bad on the third try"


def test_the_breaker_stops_calling_a_dead_upstream(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "down"})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))
    monkeypatch.setattr(llm, "_breaker", CircuitBreaker(failure_threshold=2))

    with pytest.raises(llm.LLMError):
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    before = len(calls)

    with pytest.raises(CircuitOpen):
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert len(calls) == before, "an open circuit must not touch the network"


def test_gives_up_when_every_model_is_retired(monkeypatch):
    tried = []

    def handler(request):
        tried.append(json.loads(request.content)["model"])
        return _retired()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    with pytest.raises(llm.LLMError) as exc:
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert "404" in str(exc.value)
    assert tried == ["dead-model", *llm.FALLBACK_MODELS]


def test_a_rate_limit_does_not_open_the_breaker(monkeypatch):
    # Being told to slow down is not the upstream being broken. Counting it as
    # a failure would take the app down exactly when it is busiest.
    def handler(request):
        return httpx.Response(429, json={"error": "slow down"})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))
    breaker = CircuitBreaker(failure_threshold=2)
    monkeypatch.setattr(llm, "_breaker", breaker)

    for _ in range(3):
        with pytest.raises(llm.LLMError):
            asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert breaker.state == "closed"


def test_it_waits_as_long_as_the_upstream_asked(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    def handler(request):
        if len(slept) >= 1:
            return _ok()
        return httpx.Response(429, json={"error": {
            "message": "Rate limit reached ... Please try again in 4.5s."}})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)

    asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert slept and 4.5 <= slept[0] <= 6, "should honour the stated wait, not guess"


def test_a_retry_after_header_wins_over_the_message(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    def handler(request):
        if len(slept) >= 1:
            return _ok()
        return httpx.Response(429, headers={"retry-after": "12"},
                              json={"error": {"message": "try again in 1s"}})

    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)

    asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert slept[0] >= 12
