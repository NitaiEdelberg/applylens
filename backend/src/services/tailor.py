"""Generate CV-grounded resume bullets + a cover letter, then verify grounding."""
from ..llm import chat_json
from .grounding import check_grounding

SYSTEM = (
    "You tailor a candidate's real experience to a target job. "
    "CRITICAL: use ONLY facts present in the CV. Never invent skills, tools, "
    "employers, titles, or metrics. Respond with JSON only."
)


async def tailor(jd_text: str, cv_text: str) -> dict:
    prompt = f"""Using ONLY what is in the CV, write:
- bullets: 4-6 resume bullet strings tailored to this job (impact-oriented, start with a verb)
- cover_letter: a short 3-paragraph cover letter

Do not claim any skill, tool, employer, or number that is not in the CV.

JOB:
\"\"\"{jd_text}\"\"\"

CV:
\"\"\"{cv_text}\"\"\"

Return JSON: {{"bullets": [str], "cover_letter": str}}"""
    data = await chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.4,
    )
    bullets = data.get("bullets", []) or []
    cover_letter = data.get("cover_letter", "")

    # Guardrail: fact-check every generated bullet against the CV.
    grounding = await check_grounding(cv_text, bullets)
    flagged = [g for g in grounding if not g["supported"]]

    return {
        "bullets": bullets,
        "cover_letter": cover_letter,
        "grounding": grounding,
        "flagged_count": len(flagged),
    }


# Bounded self-correction: 1 initial regeneration + at most 1 retry.
_MAX_ATTEMPTS = 2

_REGEN_SYSTEM = (
    "You rewrite a single resume bullet so it is tailored to a target job while "
    "using ONLY facts present in the candidate's CV. A prior version of this "
    "bullet was flagged by a fact-checker for making a claim the CV does not "
    "support. Rewrite it to keep the JD relevance but drop or replace the "
    "unsupported claim with something the CV actually backs. Never invent skills, "
    "tools, employers, titles, or metrics. Respond with JSON only."
)


async def _generate_replacement(jd_text: str, cv_text: str, bullet: str, issue: str) -> str:
    """Ask the model for ONE replacement bullet, conditioned on the failure reason."""
    issue_line = (
        f'The previous bullet was flagged for this specific problem:\n"""{issue}"""\n'
        "You MUST avoid that problem in your rewrite."
        if issue and issue.strip()
        else "The previous bullet was flagged as not supported by the CV. "
        "Rewrite it using only claims the CV clearly backs."
    )
    prompt = f"""Rewrite ONE resume bullet.

{issue_line}

Rules:
- Stay tailored to the JOB below (impact-oriented, start with a verb).
- Use ONLY facts present in the CV. Do not claim any skill, tool, employer,
  title, or number that is not in the CV.
- Return exactly one replacement bullet.

JOB:
\"\"\"{jd_text}\"\"\"

CV:
\"\"\"{cv_text}\"\"\"

PREVIOUS (flagged) BULLET:
\"\"\"{bullet}\"\"\"

Return JSON: {{"bullet": str}}"""
    data = await chat_json(
        [
            {"role": "system", "content": _REGEN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return (data.get("bullet") or "").strip()


async def regenerate_bullet(jd_text: str, cv_text: str, bullet: str, issue: str) -> dict:
    """Closed detection -> repair -> re-verification loop for a single bullet.

    Regenerates the bullet conditioned on the flagged `issue`, then INDEPENDENTLY
    re-checks the new bullet with check_grounding (never trusting the generation
    step). If still unsupported, retries once more; after the bound, returns the
    best attempt with its honest verdict — never fabricating a green.
    """
    current_issue = issue or ""
    best = None
    for _ in range(_MAX_ATTEMPTS):
        new_bullet = await _generate_replacement(jd_text, cv_text, bullet, current_issue)
        checks = await check_grounding(cv_text, [new_bullet])
        grounding = checks[0] if checks else {
            "statement": new_bullet,
            "supported": False,
            "evidence": None,
            "issue": "Could not verify the regenerated bullet.",
        }
        best = {"bullet": new_bullet, "grounding": grounding}
        if grounding.get("supported"):
            return best
        # Feed the fresh failure reason back into the next attempt.
        current_issue = grounding.get("issue") or current_issue
    return best
