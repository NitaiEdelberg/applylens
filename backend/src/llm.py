"""Thin async wrapper around Groq's OpenAI-compatible chat API.

What this file guards against, in the order the problems actually happened:

  a retired model   Groq retired llama-3.3-70b-versatile on the free tier on
                    2026-06-17. It surfaces only at request time, as a 404
                    model_not_found, so one stale id in an env var took every
                    endpoint down at once. Hence the fallback chain.
  a rate limit      A 429 is not a reason to give up, and it is not a reason to
                    try a different model either. Retry the same one, backing
                    off with jitter.
  an outage         When the upstream is down, failing fast beats paying the
                    timeout on every request. Hence the circuit breaker.
  invalid JSON      Asking a model to "respond with JSON only" and then parsing
                    the reply is a failure mode you can delete: send a schema
                    and let the decoder enforce it. Not every model supports
                    that, so an unsupported schema degrades to JSON mode rather
                    than failing the request.
"""
import asyncio
import json
import os
import random
import re
import time

import httpx

from . import cassette
from .config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL
from .resilience import CircuitBreaker, CircuitOpen
from .trace import record_llm_call


class LLMError(Exception):
    pass


# Groq retires models on the free tier and the retirement shows up only at
# request time. A dead id would take every endpoint down at once, and it can
# live in a deployed env var we can't edit from here, so try the configured
# model first and then fall through this list.
FALLBACK_MODELS = ["openai/gpt-oss-120b", "llama-3.1-8b-instant"]

# One model call, not one request: four of these run per analyze.
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_SECONDS", "0.75"))

# The first model that answered, remembered so the rest of the process skips
# the dead ones instead of paying a failed round-trip per call.
_working_model = None
# Set once a schema request comes back rejected, so we stop asking.
_schema_supported = True

_breaker = CircuitBreaker(
    failure_threshold=int(os.getenv("LLM_BREAKER_FAILURES", "4")),
    cooldown_seconds=float(os.getenv("LLM_BREAKER_COOLDOWN", "30")),
)


def _candidates():
    """Models to try, in order, without repeats."""
    if _working_model:
        return [_working_model]
    seen, out = set(), []
    for name in [GROQ_MODEL, *FALLBACK_MODELS]:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _model_is_gone(status: int, body: str) -> bool:
    """True when the failure is 'this model id no longer exists'."""
    if status not in (400, 404):
        return False
    body = body.lower()
    return ("model_not_found" in body or "does not exist" in body
            or "decommissioned" in body)


def _schema_rejected(status: int, body: str) -> bool:
    """True when the model took the request but not the response_format."""
    if status != 400:
        return False
    body = body.lower()
    return "response_format" in body or "json_schema" in body or "schema" in body


def _is_transient(status: int) -> bool:
    """Worth trying the same model again: rate limits and server-side faults."""
    return status == 429 or 500 <= status < 600


# Groq says exactly how long to wait ("Please try again in 2.58s"). Guessing an
# exponential backoff when the server has told you the number is silly, and on
# the free tier's per-minute token budget the guess is usually far too short.
_RETRY_HINT = re.compile(r"try again in ([\d.]+)\s*s", re.IGNORECASE)


def _retry_after(headers, body: str):
    """Seconds the upstream asked us to wait, if it said."""
    header = headers.get("retry-after") if headers else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    found = _RETRY_HINT.search(body or "")
    return float(found.group(1)) if found else None


def _response_format(json_mode: bool, schema):
    if schema and _schema_supported:
        return {"type": "json_schema",
                "json_schema": {"name": "response", "schema": schema, "strict": False}}
    if json_mode:
        return {"type": "json_object"}
    return None


async def chat(messages, temperature=0.2, json_mode=True, schema=None) -> str:
    """One chat completion, with model fallback, retries and a breaker.

    `schema` is a JSON Schema for the reply. When the model supports
    schema-constrained decoding the reply cannot come back malformed; when it
    doesn't, this falls back to plain JSON mode for the rest of the process.
    """
    global _working_model, _schema_supported

    base = {"temperature": temperature, "messages": messages}
    fmt_for_key = _response_format(json_mode, schema)
    tape_key = cassette.key_for(messages, temperature, fmt_for_key) if cassette.enabled() else None

    # Replay never touches the network, and a miss is an error rather than a
    # quiet live call.
    if tape_key and cassette.MODE == "replay":
        record_llm_call("cassette", None, 0.0)
        return cassette.playback(tape_key)

    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set (see backend/.env.example)")

    _breaker.before_call()
    last_error = None
    last_status = None

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for model in _candidates():
            for attempt in range(1, MAX_ATTEMPTS + 1):
                body = dict(base, model=model)
                fmt = _response_format(json_mode, schema)
                if fmt:
                    body["response_format"] = fmt

                started = time.monotonic() * 1000
                try:
                    resp = await client.post(
                        GROQ_URL,
                        headers={"Authorization": "Bearer " + GROQ_API_KEY},
                        json=body,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_status = 0
                    record_llm_call(model, None, time.monotonic() * 1000 - started,
                                    status=0, retried=attempt > 1)
                    last_error = "Groq unreachable: {}".format(exc)
                    _breaker.record_failure()
                    if attempt < MAX_ATTEMPTS:
                        await _backoff(attempt)
                        continue
                    break

                elapsed = time.monotonic() * 1000 - started
                if resp.status_code == 200:
                    data = resp.json()
                    record_llm_call(model, data.get("usage"), elapsed,
                                    retried=attempt > 1)
                    _working_model = model
                    _breaker.record_success()
                    content = data["choices"][0]["message"]["content"]
                    if tape_key and cassette.MODE == "record":
                        cassette.record(tape_key, content, model, data.get("usage"))
                    return content

                record_llm_call(model, None, elapsed, status=resp.status_code,
                                retried=attempt > 1)
                text = resp.text[:300]
                last_status = resp.status_code
                last_error = "Groq API {}: {}".format(resp.status_code, text)

                # An unsupported schema is our fault, not the upstream's: drop
                # the schema and try the same model again without counting it
                # against the breaker.
                if schema and _schema_supported and _schema_rejected(resp.status_code, text):
                    _schema_supported = False
                    continue

                if _is_transient(resp.status_code):
                    # A rate limit means we are asking too fast, not that the
                    # upstream is broken: counting it as a breaker failure would
                    # take the app down during its busiest minute.
                    if resp.status_code != 429:
                        _breaker.record_failure()
                    if attempt < MAX_ATTEMPTS:
                        await _backoff(attempt, _retry_after(resp.headers, text))
                        continue
                    break

                if _model_is_gone(resp.status_code, text):
                    break  # next model in the chain

                _breaker.record_failure()
                raise LLMError(last_error)

    # Same reasoning as inside the loop: exhausting the retries against a rate
    # limit says we were too fast, not that the upstream is down.
    if last_status != 429:
        _breaker.record_failure()
    raise LLMError(last_error or "No usable Groq model")


async def _backoff(attempt: int, asked_for=None) -> None:
    """Wait as long as the upstream asked, else exponential with jitter.

    The jitter matters because analyze fires three stages at once: without it
    they retry in lockstep and hit the same limit together.
    """
    if asked_for:
        await asyncio.sleep(min(asked_for + 0.25, 60) * (1 + 0.1 * random.random()))
        return
    delay = BACKOFF_BASE * (2 ** (attempt - 1))
    await asyncio.sleep(delay * (0.5 + random.random()))


async def chat_json(messages, temperature=0.2, schema=None) -> dict:
    """Call the model in JSON mode and parse the result."""
    content = await chat(messages, temperature=temperature, json_mode=True, schema=schema)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError("Model did not return valid JSON: {}".format(exc)) from exc


__all__ = ["chat", "chat_json", "LLMError", "CircuitOpen", "FALLBACK_MODELS"]
