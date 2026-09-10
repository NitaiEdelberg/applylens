"""Turn a raw job description into structured requirements."""
from ..llm import chat_json
from .untrusted import GUARD, as_data

SYSTEM = (
    "You extract structured hiring requirements from a job description. "
    "Respond with JSON only. " + GUARD
)

# The shape is enforced by the decoder where the model supports it, so a
# malformed reply is not a failure mode we have to catch. See llm.chat.
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "seniority": {"type": "string"},
        "must_haves": {"type": "array", "items": {"type": "string"}},
        "nice_to_haves": {"type": "array", "items": {"type": "string"}},
        "stack": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "must_haves"],
}


async def extract_job(jd_text: str) -> dict:
    prompt = f"""Extract the job description below into JSON with exactly these keys:
- title (string)
- seniority (string, e.g. "junior", "mid", "senior", or "" if unclear)
- must_haves (array of short skill/requirement strings)
- nice_to_haves (array of short skill strings)
- stack (array of concrete technologies/tools mentioned)

Keep each item short (a few words). Do not invent requirements that aren't in the text.

JOB DESCRIPTION:
{as_data("JOB_DESCRIPTION", jd_text)}"""
    data = await chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.1,
        schema=SCHEMA,
    )
    # normalize
    return {
        "title": data.get("title", ""),
        "seniority": data.get("seniority", ""),
        "must_haves": data.get("must_haves", []) or [],
        "nice_to_haves": data.get("nice_to_haves", []) or [],
        "stack": data.get("stack", []) or [],
    }
