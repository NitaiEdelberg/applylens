"""Generate CV-grounded resume bullets + a cover letter, then verify grounding."""
import asyncio

from ..llm import chat_json
from .grounding import check_grounding, check_cover_letter

SYSTEM = (
    "You are an expert resume writer. You TAILOR a candidate's real experience to a "
    "specific target job: you reframe, rephrase, reorder, and emphasize their CV so "
    "it speaks directly to what THIS job asks for. You must stay truthful — every "
    "claim must be grounded in the CV — but you must NOT simply copy CV sentences: "
    "adapt them to the job. Respond with JSON only."
)


async def tailor(jd_text: str, cv_text: str) -> dict:
    prompt = f"""Write 4-6 tailored resume bullets and a short 3-paragraph cover letter for THIS job, drawing only on the candidate's CV.

TAILORING (target the job, but only by re-expressing what the CV already says):
- REFRAME, don't copy: reword the candidate's real experience with stronger verbs, tighter phrasing, and emphasis aimed at this job. Do NOT repeat CV sentences verbatim.
- Prioritize & reorder: lead with the CV experience this job cares about most; put the most job-relevant bullets first.
- Use the job's terminology ONLY where the CV genuinely describes that same skill/experience.

STAY VERIFIABLE (non-negotiable — every bullet is fact-checked against the CV):
- Same facts as the CV, re-expressed — NOT new claims. Each phrase must be verifiable against the CV.
- Do NOT add skills, tools, or technologies the job wants but the CV lacks (e.g. don't claim "REST APIs" if the CV never mentions them).
- Do NOT add embellishments, outcomes, or adjectives the CV doesn't state (no "scalable", "seamless", "engaging", "drove business value", invented metrics, etc.).
- If in doubt, prefer a faithful rewording over an impressive-sounding claim.

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

    # Guardrail: fact-check every generated bullet AND the cover letter's
    # factual self-claims against the CV — concurrently.
    grounding, cover = await asyncio.gather(
        check_grounding(cv_text, bullets),
        check_cover_letter(cv_text, cover_letter),
    )
    flagged = [g for g in grounding if not g["supported"]]

    return {
        "bullets": bullets,
        "cover_letter": cover_letter,
        "grounding": grounding,
        "flagged_count": len(flagged),
        "cover_grounding": cover["claims"],
        "cover_flagged_count": cover["flagged_count"],
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
