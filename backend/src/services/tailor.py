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
