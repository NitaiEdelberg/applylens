"""Grounding guardrail: flag any generated statement not supported by the CV.

This is ApplyLens's safety layer — it prevents the tailoring step from inventing
skills, tools, employers, or metrics the candidate doesn't actually have.
"""
from __future__ import annotations

import json
from ..llm import chat_json

SYSTEM = (
    "You are a strict fact-checker that prevents resume fabrication. "
    "A statement is SUPPORTED only if the CV contains evidence for every specific "
    "claim it makes (skill, tool, employer, title, metric). If any part is not in "
    "the CV, it is NOT supported. Respond with JSON only."
)


async def check_grounding(cv_text: str, statements: list[str]) -> list[dict]:
    if not statements:
        return []
    prompt = f"""For each candidate statement, decide if the CV supports it.
Return JSON: {{"checks": [{{"statement": str, "supported": bool,
"evidence": str or null, "issue": str or null}}]}}
- evidence: the CV text that backs it (when supported)
- issue: what specifically is unsupported/invented (when not supported)

CV:
\"\"\"{cv_text}\"\"\"

STATEMENTS:
{json.dumps(statements, ensure_ascii=False)}"""
    data = await chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.0,
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
