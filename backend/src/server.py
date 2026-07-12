"""ApplyLens API — JD extraction, CV fit-scoring, and grounded tailoring."""
import asyncio
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .llm import LLMError
from .schemas import (
    ExtractRequest,
    AnalyzeRequest,
    ExtractedJob,
    FitResult,
    TailorResult,
    AnalyzeResponse,
    RegenerateBulletRequest,
    RegenerateBulletResponse,
)
from .services.extract import extract_job
from .services.fit import score_fit
from .services.tailor import tailor, regenerate_bullet

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title="ApplyLens", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/extract", response_model=ExtractedJob)
async def api_extract(req: ExtractRequest):
    _require(req.jd_text, "jd_text")
    return _guard(await _safe(extract_job, req.jd_text))


@app.post("/api/fit", response_model=FitResult)
async def api_fit(req: AnalyzeRequest):
    _require(req.jd_text, "jd_text")
    _require(req.cv_text, "cv_text")
    return _guard(await _safe(score_fit, req.jd_text, req.cv_text))


@app.post("/api/tailor", response_model=TailorResult)
async def api_tailor(req: AnalyzeRequest):
    _require(req.jd_text, "jd_text")
    _require(req.cv_text, "cv_text")
    return _guard(await _safe(tailor, req.jd_text, req.cv_text))


@app.post("/api/regenerate-bullet", response_model=RegenerateBulletResponse)
async def api_regenerate_bullet(req: RegenerateBulletRequest):
    """Self-correcting loop: regenerate one flagged bullet, then re-verify it."""
    _require(req.jd_text, "jd_text")
    _require(req.cv_text, "cv_text")
    _require(req.bullet, "bullet")
    return _guard(
        await _safe(regenerate_bullet, req.jd_text, req.cv_text, req.bullet, req.issue)
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def api_analyze(req: AnalyzeRequest):
    """Run extraction, fit-scoring, and tailoring concurrently in one call."""
    _require(req.jd_text, "jd_text")
    _require(req.cv_text, "cv_text")
    job, fit, tailored = await _safe(
        _gather_analyze, req.jd_text, req.cv_text
    )
    return AnalyzeResponse(job=job, fit=fit, tailor=tailored)


async def _gather_analyze(jd_text: str, cv_text: str):
    return await asyncio.gather(
        extract_job(jd_text),
        score_fit(jd_text, cv_text),
        tailor(jd_text, cv_text),
    )


# ---- helpers ----
def _require(value: str, name: str):
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=f"'{name}' is required")


async def _safe(fn, *args):
    try:
        return await fn(*args)
    except LLMError as exc:
        logging.warning("LLM error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _guard(result):
    return result
