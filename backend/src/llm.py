"""Thin async wrapper around Groq's OpenAI-compatible chat API."""
import json
import httpx

from .config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL


class LLMError(Exception):
    pass


# Groq retires models on the free tier (llama-3.3-70b-versatile was retired on
# 2026-06-17) and the retirement shows up only at request time, as a 404
# model_not_found. A dead id therefore takes every endpoint down at once, and
# the id can live in a deployed env var we can't edit from here. So try the
# configured model first, then fall through the list below.
FALLBACK_MODELS = ["openai/gpt-oss-120b", "llama-3.1-8b-instant"]

# The first model that answered, remembered so the rest of the process skips
# the dead ones instead of paying a failed round-trip per call.
_working_model = None


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


def _model_is_gone(resp) -> bool:
    """True when the failure is 'this model id no longer exists', not a real error."""
    if resp.status_code not in (400, 404):
        return False
    body = resp.text.lower()
    return "model_not_found" in body or "does not exist" in body or "decommissioned" in body


async def chat(messages, temperature=0.2, json_mode=True) -> str:
    global _working_model

    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set (see backend/.env.example)")

    body = {"temperature": temperature, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_error = None
    async with httpx.AsyncClient(timeout=60) as client:
        for model in _candidates():
            resp = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={**body, "model": model},
            )
            if resp.status_code == 200:
                _working_model = model
                return resp.json()["choices"][0]["message"]["content"]
            last_error = f"Groq API {resp.status_code}: {resp.text[:300]}"
            if not _model_is_gone(resp):
                raise LLMError(last_error)

    raise LLMError(f"No usable Groq model. Last error: {last_error}")


async def chat_json(messages, temperature=0.2) -> dict:
    """Call the model in JSON mode and parse the result."""
    content = await chat(messages, temperature=temperature, json_mode=True)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return valid JSON: {exc}") from exc
