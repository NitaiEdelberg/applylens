"""ApplyLens API — JD extraction, CV fit-scoring, and grounded tailoring."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from .llm import LLMError
from .db_sql import TrackedApplication, User, get_session, init_db
from .security import create_token, decode_token, hash_password, verify_password
from .services.resume import ResumeParseError, extract_text
from .schemas import (
    ExtractRequest,
    AnalyzeRequest,
    ExtractedJob,
    FitResult,
    TailorResult,
    AnalyzeResponse,
    RegenerateBulletRequest,
    RegenerateBulletResponse,
    AuthRequest,
    TokenResponse,
    TrackerCreate,
    TrackerStatusUpdate,
    TrackedApp,
)
from .services.extract import extract_job
from .services.fit import score_fit
from .services.tailor import tailor, regenerate_bullet
from .services.skillmatch import skill_match
from .services.rag import retrieve_context, default_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create the accounts/tracker tables on boot. Uses SQLite locally (no
    # credential) or Postgres when DATABASE_URL is set — see db_sql.py.
    init_db()
    yield


app = FastAPI(title="ApplyLens", version="0.1.0", lifespan=lifespan)
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


# Max upload size for a resume file. Resumes are small; 2 MB is generous and
# keeps memory trivial on the free-tier box.
MAX_RESUME_BYTES = 2 * 1024 * 1024


@app.post("/api/parse-resume")
async def api_parse_resume(file: UploadFile = File(...)):
    """Extract plain text from an uploaded PDF/DOCX so it can fill the CV field.

    Pure parsing (no LLM). Every failure is a friendly 400 — never a 500.
    """
    name = file.filename or ""
    lname = name.lower()
    if not (lname.endswith(".pdf") or lname.endswith(".docx")):
        raise HTTPException(
            status_code=400, detail="Unsupported file type — upload a PDF or DOCX"
        )

    data = await file.read()
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(
            status_code=400, detail="File is too large — please upload a file under 2 MB"
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    try:
        text = extract_text(name, data)
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — never leak a 500 for a bad file
        logging.warning("resume parse failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Couldn't read this file. Please paste your CV instead.",
        )
    return {"text": text}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def api_analyze(req: AnalyzeRequest):
    """Run extraction, fit-scoring, and tailoring concurrently in one call.

    When an optional `career_text` corpus is supplied, RAG retrieves the most
    relevant career-history chunks for this job and tailoring grounds against
    CV + retrieved chunks (a fuller, still-honest source of truth).
    """
    _require(req.jd_text, "jd_text")
    _require(req.cv_text, "cv_text")
    career_text = (req.career_text or "").strip()

    if career_text:
        rag_info, job, fit, tailored = await _safe(
            _analyze_with_rag, req.jd_text, req.cv_text, career_text
        )
    else:
        job, fit, tailored = await _safe(_gather_analyze, req.jd_text, req.cv_text)
        rag_info = {"used": False, "chunks": [], "source": default_source()}

    # Deterministic, CPU-only second opinion: TF-IDF keyword coverage of the
    # extracted requirements by the CV. No LLM call, so no extra latency.
    requirements = list(job.get("must_haves", [])) + list(job.get("nice_to_haves", []))
    match = skill_match(requirements, req.cv_text)
    return AnalyzeResponse(
        job=job, fit=fit, tailor=tailored, skill_match=match, rag=rag_info
    )


async def _gather_analyze(jd_text: str, cv_text: str):
    return await asyncio.gather(
        extract_job(jd_text),
        score_fit(jd_text, cv_text),
        tailor(jd_text, cv_text),
    )


async def _analyze_with_rag(jd_text: str, cv_text: str, career_text: str):
    """RAG-augmented analyze: extract + fit run concurrently, then retrieve
    relevant career chunks, then tailor+ground against CV + those chunks.

    Tailoring must wait for retrieval so its grounded source of truth is
    (cv_text + retrieved chunks): a bullet backed by a real retrieved experience
    is legitimately grounded; anything in neither is still flagged.
    """
    job, fit = await asyncio.gather(
        extract_job(jd_text), score_fit(jd_text, cv_text)
    )
    requirements = (
        list(job.get("must_haves", []))
        + list(job.get("nice_to_haves", []))
        + list(job.get("stack", []))
    )
    # retrieve_context is sync (CPU for TF-IDF, blocking httpx for Gemini) — run
    # it off the event loop so it never stalls the async LLM routes. (Uses
    # run_in_executor rather than asyncio.to_thread for Python 3.8 support.)
    loop = asyncio.get_running_loop()
    rag = await loop.run_in_executor(
        None, retrieve_context, requirements or jd_text, career_text, 4
    )
    chunks = rag["chunks"]
    source_text = (
        cv_text if not chunks else cv_text + "\n\n" + "\n\n".join(chunks)
    )
    tailored = await tailor(jd_text, source_text)
    rag_info = {"used": True, "chunks": chunks, "source": rag["source"]}
    return rag_info, job, fit, tailored


# ---- optional accounts + per-user cloud tracker (Circle 3) ----
# These endpoints are SYNC `def` on purpose: FastAPI runs them in a threadpool,
# so blocking SQLAlchemy calls don't stall the event loop that serves the async
# LLM routes. Accounts are OPTIONAL — the anonymous localStorage tracker keeps
# working untouched; signing in just syncs the tracker across devices.


def current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_session),
) -> User:
    """Resolve the bearer-token user, or 401. Used to scope every tracker call."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


@app.post("/api/auth/register", response_model=TokenResponse)
def api_register(req: AuthRequest, db: Session = Depends(get_session)):
    email = _normalize_email(req.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if not req.password or len(req.password) < 6:
        raise HTTPException(
            status_code=400, detail="Password must be at least 6 characters"
        )
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(email=email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(token=create_token(user.id), email=user.email)


@app.post("/api/auth/login", response_model=TokenResponse)
def api_login(req: AuthRequest, db: Session = Depends(get_session)):
    email = _normalize_email(req.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(token=create_token(user.id), email=user.email)


def _to_tracked_app(row: TrackedApplication) -> TrackedApp:
    payload = None
    if row.payload:
        try:
            payload = json.loads(row.payload)
        except (ValueError, TypeError):
            payload = None
    return TrackedApp(
        id=row.id,
        title=row.title,
        company=row.company or "",
        status=row.status,
        score=row.score,
        flagged=row.flagged or 0,
        payload=payload,
        savedAt=row.created_at.isoformat() if row.created_at else None,
    )


@app.get("/api/tracker", response_model=List[TrackedApp])
def api_tracker_list(
    user: User = Depends(current_user), db: Session = Depends(get_session)
):
    rows = db.scalars(
        select(TrackedApplication)
        .where(TrackedApplication.user_id == user.id)
        .order_by(TrackedApplication.created_at.desc(), TrackedApplication.id.desc())
    ).all()
    return [_to_tracked_app(r) for r in rows]


@app.post("/api/tracker", response_model=TrackedApp)
def api_tracker_create(
    req: TrackerCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    row = TrackedApplication(
        user_id=user.id,
        title=req.title or "Untitled role",
        company=req.company or "",
        status=req.status or "applied",
        score=req.score,
        flagged=req.flagged or 0,
        payload=json.dumps(req.payload) if req.payload is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_tracked_app(row)


def _owned_app(app_id: int, user: User, db: Session) -> TrackedApplication:
    row = db.get(TrackedApplication, app_id)
    # 404 (not 403) when it isn't theirs — don't reveal another user's row exists.
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    return row


@app.patch("/api/tracker/{app_id}", response_model=TrackedApp)
def api_tracker_update(
    app_id: int,
    req: TrackerStatusUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    row = _owned_app(app_id, user, db)
    row.status = req.status or row.status
    db.commit()
    db.refresh(row)
    return _to_tracked_app(row)


@app.delete("/api/tracker/{app_id}")
def api_tracker_delete(
    app_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    row = _owned_app(app_id, user, db)
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/keepalive")
def api_keepalive(db: Session = Depends(get_session)):
    """Trivial SELECT 1 to keep a free-tier (e.g. Supabase) DB from idle-pausing.
    Hit by a scheduled GitHub Action. Never 500s — returns {ok:false} on failure.
    """
    try:
        db.execute(sql_text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — a cron ping must never surface a 500
        logging.warning("keepalive failed: %s", exc)
        return {"ok": False}


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
