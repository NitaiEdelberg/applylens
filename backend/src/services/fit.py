"""Score how well a CV matches a job — strictly evidence-based."""
from ..llm import chat_json

SYSTEM = (
    "You score how well a candidate's CV matches a job's requirements. "
    "Be strict and evidence-based; never credit a skill the CV does not show. "
    "Respond with JSON only."
)


async def score_fit(jd_text: str, cv_text: str) -> dict:
    prompt = f"""Compare the CV against the job and return JSON with keys:
- overall_score: integer 0-100 (honest overall match)
- matched: array of {{"requirement": str, "evidence": str}} where the CV clearly supports the requirement (quote/paraphrase the CV evidence)
- partial: array of {{"requirement": str, "note": str}} for partially/indirectly supported requirements
- missing: array of requirement strings the CV does not support
- summary: 1-2 sentence honest assessment

Only use evidence actually present in the CV. Do not invent experience.

JOB:
\"\"\"{jd_text}\"\"\"

CV:
\"\"\"{cv_text}\"\"\""""
    data = await chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return {
        "overall_score": int(data.get("overall_score", 0) or 0),
        "matched": data.get("matched", []) or [],
        "partial": data.get("partial", []) or [],
        "missing": data.get("missing", []) or [],
        "summary": data.get("summary", ""),
    }
