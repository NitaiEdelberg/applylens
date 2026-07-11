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
