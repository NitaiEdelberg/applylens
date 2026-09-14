"""Recording and replaying model calls.

The property that matters most: replay must never reach the network. A
cassette that quietly falls through to a live call turns a green CI run into a
network call nobody knew they were making.
"""
import asyncio
import importlib
import json

import httpx
import pytest


def _reload(monkeypatch, tmp_path, mode):
    """Re-import the client with cassette env set, as a real run would have it."""
    tape = tmp_path / "tape.jsonl"
    monkeypatch.setenv("LLM_CASSETTE", str(tape))
    monkeypatch.setenv("LLM_CASSETTE_MODE", mode)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    import src.cassette as cassette
    import src.llm as llm
    importlib.reload(cassette)
    importlib.reload(llm)
    # The key has to be set ON the module, not only in the environment: llm
    # binds it from config at import, and config was imported once at
    # collection time — so on a machine with no .env (which is every CI
    # machine) setenv here changes nothing. That difference kept this suite
    # green locally and red on CI for seventeen runs.
    llm.GROQ_API_KEY = "test-key"
    return llm, cassette, tape


def _client(handler):
    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)
    return _Client


@pytest.fixture(autouse=True)
def restore_modules():
    yield
    # Leave the modules as the rest of the suite expects to find them.
    import src.cassette as cassette
    import src.llm as llm
    importlib.reload(cassette)
    importlib.reload(llm)


MESSAGES = [{"role": "user", "content": "Is this bullet supported? Reply json."}]


def test_recording_writes_the_reply_to_the_tape(monkeypatch, tmp_path):
    llm, cassette, tape = _reload(monkeypatch, tmp_path, "record")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client(
        lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": '{"supported": true}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3}})))

    assert asyncio.run(llm.chat(MESSAGES)) == '{"supported": true}'
    entries = [json.loads(l) for l in tape.read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["content"] == '{"supported": true}'
    assert entries[0]["usage"]["prompt_tokens"] == 11
    assert entries[0]["model"], "the tape says which model produced it"


def test_replay_returns_the_recording_without_the_network(monkeypatch, tmp_path):
    llm, cassette, tape = _reload(monkeypatch, tmp_path, "record")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client(
        lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": '{"supported": false}'}}]})))
    asyncio.run(llm.chat(MESSAGES))

    llm, cassette, _ = _reload(monkeypatch, tmp_path, "replay")

    def explode(request):
        raise AssertionError("replay must not reach the network")

    monkeypatch.setattr(llm.httpx, "AsyncClient", _client(explode))
    assert asyncio.run(llm.chat(MESSAGES)) == '{"supported": false}'


def test_replay_without_a_key_still_works(monkeypatch, tmp_path):
    llm, _, _ = _reload(monkeypatch, tmp_path, "record")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})))
    asyncio.run(llm.chat(MESSAGES))

    llm, _, _ = _reload(monkeypatch, tmp_path, "replay")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    importlib.reload(llm)
    llm.GROQ_API_KEY = ""  # genuinely keyless, whatever the machine has
    assert asyncio.run(llm.chat(MESSAGES)) == "hi", "the point is CI with no key"


def test_a_missing_recording_is_loud(monkeypatch, tmp_path):
    llm, cassette, _ = _reload(monkeypatch, tmp_path, "replay")
    with pytest.raises(cassette.CassetteMiss) as exc:
        asyncio.run(llm.chat([{"role": "user", "content": "never recorded"}]))
    assert "re-record" in str(exc.value).lower()


def test_a_different_prompt_is_a_different_recording(monkeypatch, tmp_path):
    llm, cassette, _ = _reload(monkeypatch, tmp_path, "record")
    replies = iter(['{"a": 1}', '{"b": 2}'])
    monkeypatch.setattr(llm.httpx, "AsyncClient", _client(
        lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": next(replies)}}]})))
    asyncio.run(llm.chat([{"role": "user", "content": "first json"}]))
    asyncio.run(llm.chat([{"role": "user", "content": "second json"}]))

    llm, _, _ = _reload(monkeypatch, tmp_path, "replay")
    assert asyncio.run(llm.chat([{"role": "user", "content": "first json"}])) == '{"a": 1}'
    assert asyncio.run(llm.chat([{"role": "user", "content": "second json"}])) == '{"b": 2}'


def test_the_key_ignores_which_model_answered(monkeypatch, tmp_path):
    # A recording made while the fallback chain was on one model must still
    # replay after the chain moves to another.
    llm, cassette, _ = _reload(monkeypatch, tmp_path, "record")
    fmt = {"type": "json_object"}
    first = cassette.key_for(MESSAGES, 0.2, fmt)
    second = cassette.key_for(MESSAGES, 0.2, fmt)
    assert first == second
    assert cassette.key_for(MESSAGES, 0.9, fmt) != first, "temperature is part of the request"
