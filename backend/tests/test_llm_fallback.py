"""The Groq model id can go stale (llama-3.3-70b-versatile was retired on the
free tier on 2026-06-17) and the failure only shows up as a 404 at request
time, so chat() has to fall through to a live model instead of erroring out.

Sync tests driving asyncio.run, so this needs no pytest-asyncio plugin.
"""
import asyncio
import json

import httpx
import pytest

from src import llm


def _fake_groq(handler):
    """An httpx.AsyncClient stand-in wired to a fake Groq endpoint."""
    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return _Client


def _ok():
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})


def _retired():
    return httpx.Response(404, json={"error": {
        "message": "The model `x` does not exist or you do not have access to it.",
        "code": "model_not_found"}})


@pytest.fixture
def groq(monkeypatch):
    """Records the model ids tried; every id but openai/gpt-oss-120b is retired."""
    tried = []

    def handler(request):
        model = json.loads(request.content)["model"]
        tried.append(model)
        return _ok() if model == "openai/gpt-oss-120b" else _retired()

    monkeypatch.setattr(llm, "_working_model", None)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GROQ_MODEL", "dead-model")
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


def test_real_errors_still_raise(monkeypatch):
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "rate limit"}})

    monkeypatch.setattr(llm, "_working_model", None)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    with pytest.raises(llm.LLMError) as exc:
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert "429" in str(exc.value)


def test_gives_up_when_every_model_is_retired(monkeypatch):
    def handler(request):
        return _retired()

    monkeypatch.setattr(llm, "_working_model", None)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GROQ_MODEL", "dead-model")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _fake_groq(handler))

    with pytest.raises(llm.LLMError) as exc:
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert "No usable Groq model" in str(exc.value)
