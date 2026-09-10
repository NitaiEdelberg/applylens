"""Grounding guardrail: flag any generated statement not supported by the CV.

This is ApplyLens's safety layer — it prevents the tailoring step from inventing
skills, tools, employers, or metrics the candidate doesn't actually have.
"""
from __future__ import annotations

import json
from ..llm import chat_json
from ..prompts import render
from .untrusted import GUARD, as_data

# The grounding prompt lives in backend/prompts/grounding/*.txt: it is the
# guardrail's whole behaviour, so a change to it is an experiment with a
# measured before and after, not an edit. PROMPT_GROUNDING_VERSION picks one.
CHECKS_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "supported": {"type": "boolean"},
                "evidence": {"type": ["string", "null"]},
                "issue": {"type": ["string", "null"]},
            },
            "required": ["statement", "supported"]}},
    },
    "required": ["checks"],
}


async def check_grounding(cv_text: str, statements: list, version: str = None) -> list:
    if not statements:
        return []
    system, prompt = render(
        "grounding", version,
        guard=GUARD,
        cv=as_data("CV", cv_text),
        statements=json.dumps(statements, ensure_ascii=False),
    )
    data = await chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=0.0,
        schema=CHECKS_SCHEMA,
    )
    checks = data.get("checks", []) or []
    # be tolerant of a model that returns the wrong length
    normalized = []
    for i, stmt in enumerate(statements):
        c = checks[i] if i < len(checks) else {}
        normalized.append({
            "statement": c.get("statement", stmt),
            "supported": bool(c.get("supported", False)),
            "evidence": c.get("evidence"),
            "issue": c.get("issue"),
        })
    return normalized


# ---- cover-letter fact-checking ----
# A cover letter legitimately contains non-CV sentences (greetings, enthusiasm,
# aspirations, statements about the company). Running raw sentence grounding on
# it would false-flag that boilerplate. Instead we FIRST extract only the
# concrete factual claims the letter makes about the candidate's own background,
# then ground-check ONLY those.
_EXTRACT_SYSTEM = (
    "You extract, from a cover letter, ONLY the concrete factual claims the "
    "writer makes about their OWN background: skills, tools, technologies, "
    "employers, job titles, projects, and metrics. "
    "IGNORE and DO NOT extract: greetings and sign-offs, expressions of "
    "enthusiasm or excitement, aspirations and goals, opinions, generic filler, "
    "and anything about the company, role, or team being applied to. "
    "Only extract checkable, verifiable statements about the candidate's actual "
    "experience. If the letter makes no such claims, return an empty list. "
    "Respond with JSON only."
)


async def extract_claims(cover_letter: str) -> list[str]:
    """Pull only the concrete, checkable self-claims from a cover letter.

    Returns [] when the letter is pure boilerplate (greetings, enthusiasm,
    statements about the company) — so those lines never reach the grounding
    check and are never false-flagged.
    """
    if not cover_letter or not cover_letter.strip():
        return []
    prompt = f"""Extract the candidate's concrete factual self-claims from this cover letter.

Return JSON: {{"claims": [str]}}
- Each claim: one specific, checkable statement about the candidate's own
  skills, tools, employers, titles, projects, or metrics.
- Do NOT include greetings, enthusiasm/aspiration, opinions, generic statements,
  or anything about the company/role.
- If there are no such claims, return {{"claims": []}}.

COVER LETTER:
\"\"\"{cover_letter}\"\"\""""
    data = await chat_json(
        [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    claims = data.get("claims", []) or []
    # Keep only non-empty strings.
    return [c.strip() for c in claims if isinstance(c, str) and c.strip()]


async def check_cover_letter(cv_text: str, cover_letter: str) -> dict:
    """Fact-check ONLY the candidate's factual claims in a cover letter.

    extract_claims (drop boilerplate) -> check_grounding (verify vs CV).
    Returns {"claims": [<GroundingCheck dicts>], "flagged_count": <n unsupported>}.
    """
    claims = await extract_claims(cover_letter)
    if not claims:
        return {"claims": [], "flagged_count": 0}
    checks = await check_grounding(cv_text, claims)
    flagged = [c for c in checks if not c["supported"]]
    return {"claims": checks, "flagged_count": len(flagged)}
