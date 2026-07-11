"""Thin async wrapper around Groq's OpenAI-compatible chat API."""
import json
import httpx

from .config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL


class LLMError(Exception):
    pass


async def chat(messages, temperature=0.2, json_mode=True) -> str:
    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set (see backend/.env.example)")

    body = {"model": GROQ_MODEL, "temperature": temperature, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json=body,
        )
    if resp.status_code != 200:
        raise LLMError(f"Groq API {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


async def chat_json(messages, temperature=0.2) -> dict:
    """Call the model in JSON mode and parse the result."""
    content = await chat(messages, temperature=temperature, json_mode=True)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return valid JSON: {exc}") from exc
