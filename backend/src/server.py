"""ApplyLens API — JD extraction, CV fit-scoring, and grounded tailoring."""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select, text as sql_text
from sqlalchemy.orm import Session

from .cache import ResultCache, fingerprint
from .llm import LLMError
from .resilience import CircuitOpen
from .trace import log_event, start_trace, traced
from .db_sql import GuardrailFeedback, TrackedApplication, User, get_session, init_db
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
    GroundingFeedback,
    RequestTrace,
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
from .services.redact import redact, restore_deep, summary as redaction_summary
from .services.screen import screen_input
from .services import search as es_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create the accounts/tracker tables on boot. Uses SQLite locally (no
    # credential) or Postgres when DATABASE_URL is set — see db_sql.py.
    init_db()
    yield


# Repeat analyses are served from here. Sized for one free instance: 64 entries
# of a few KB each, an hour of life, gone when the instance sleeps.
_analysis_cache = ResultCache(
    max_entries=int(os.getenv("ANALYSIS_CACHE_ENTRIES", "64")),
    ttl_seconds=float(os.getenv("ANALYSIS_CACHE_TTL_SECONDS", "3600")),
)

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

    trace = start_trace("analyze")

    # The same CV against the same job produces the same four model calls and
    # the same answer, so serve the repeat from memory. The trace still comes
    # back, marked cached, so the caller can see why it was instant.
    key = fingerprint(req.jd_text, req.cv_text, career_text)
    hit = _analysis_cache.get(key)
    if hit is not None:
        log_event("analyze.cache_hit", key=key)
        cached = RequestTrace(**dict(trace.as_dict(), cached=True))
        return hit.model_copy(update={"trace": cached})

    # Personal details are stripped before anything leaves this box, and put
    # back on the way out. The analysis never needed the phone number.
    cv_text, personal = redact(req.cv_text)
    career_text, career_personal = redact(career_text)
    personal.update(career_personal)

    # The job description is text someone copied off a website: screen it for
    # instructions aimed at the model. This never blocks — it reports.
    screening = await traced("screen", screen_input, req.jd_text, "job description")

    if career_text:
        rag_info, job, fit, tailored = await _safe(
            _analyze_with_rag, req.jd_text, cv_text, career_text
        )
    else:
        job, fit, tailored = await _safe(_gather_analyze, req.jd_text, cv_text)
        rag_info = {"used": False, "chunks": [], "source": default_source()}

    job, fit, tailored, rag_info = restore_deep(
        [job, fit, tailored, rag_info], personal
    )

    # Deterministic, CPU-only second opinion: term coverage of the extracted
    # requirements by the CV. No LLM call, so no extra latency.
    requirements = list(job.get("must_haves", [])) + list(job.get("nice_to_haves", []))
    match = skill_match(requirements, req.cv_text)
    response = AnalyzeResponse(
        job=job, fit=fit, tailor=tailored, skill_match=match, rag=rag_info,
        trace=trace.as_dict(),
        screening=screening,
        privacy={"redacted": redaction_summary(personal)},
    )
    _analysis_cache.set(key, response)
    log_event("analyze.done", **trace.as_dict()["totals"])
    return response


async def _gather_analyze(jd_text: str, cv_text: str):
    return await asyncio.gather(
        traced("extract", extract_job, jd_text),
        traced("fit", score_fit, jd_text, cv_text),
        traced("tailor", tailor, jd_text, cv_text),
    )


async def _analyze_with_rag(jd_text: str, cv_text: str, career_text: str):
    """RAG-augmented analyze: extract + fit run concurrently, then retrieve
    relevant career chunks, then tailor+ground against CV + those chunks.

    Tailoring must wait for retrieval so its grounded source of truth is
    (cv_text + retrieved chunks): a bullet backed by a real retrieved experience
    is legitimately grounded; anything in neither is still flagged.
    """
    job, fit = await asyncio.gather(
        traced("extract", extract_job, jd_text),
        traced("fit", score_fit, jd_text, cv_text),
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
    rag = await traced(
        "retrieve",
        loop.run_in_executor,
        None, retrieve_context, requirements or jd_text, career_text, 4,
    )
    chunks = rag["chunks"]
    source_text = (
        cv_text if not chunks else cv_text + "\n\n" + "\n\n".join(chunks)
    )
    tailored = await traced("tailor", tailor, jd_text, source_text)
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


@app.get("/api/tracker/search", response_model=List[TrackedApp])
def api_tracker_search(
    q: str = "",
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    """Full-text search over the signed-in user's tracked applications.

    When Elasticsearch is configured it ranks via ES (user-scoped) and this
    endpoint fetches those rows from the DB preserving the ES relevance order.
    On any ES failure OR when ES is disabled it FALLS BACK to a case-insensitive
    substring match on title/company — so search is always available and fully
    testable with no ES instance. An empty query returns all the user's apps,
    newest first (same shape as GET /api/tracker)."""
    query = (q or "").strip()

    # Empty query -> everything, newest first.
    if not query:
        rows = db.scalars(
            select(TrackedApplication)
            .where(TrackedApplication.user_id == user.id)
            .order_by(
                TrackedApplication.created_at.desc(), TrackedApplication.id.desc()
            )
        ).all()
        return [_to_tracked_app(r) for r in rows]

    # Try Elasticsearch first; fall back to the DB on disabled/unavailable.
    if es_search.es_enabled():
        try:
            ids = es_search.search_apps(user.id, query)
            if not ids:
                return []
            rows = db.scalars(
                select(TrackedApplication).where(
                    TrackedApplication.user_id == user.id,
                    TrackedApplication.id.in_(ids),
                )
            ).all()
            # Preserve ES relevance order and stay user-scoped (a row that isn't
            # this user's — or was deleted — simply doesn't appear).
            by_id = {r.id: r for r in rows}
            ordered = [by_id[i] for i in ids if i in by_id]
            return [_to_tracked_app(r) for r in ordered]
        except es_search.SearchUnavailable:
            pass  # degrade to the DB substring match below

    # DB fallback: case-insensitive substring match on title/company, newest first.
    like = f"%{query}%"
    rows = db.scalars(
        select(TrackedApplication)
        .where(
            TrackedApplication.user_id == user.id,
            or_(
                TrackedApplication.title.ilike(like),
                TrackedApplication.company.ilike(like),
            ),
        )
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
    es_search.index_app(row)  # best-effort; never raises, never blocks the save
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
    es_search.index_app(row)  # best-effort re-index on status change
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
    es_search.delete_app(app_id)  # best-effort remove from the index; non-fatal
    return {"ok": True}


@app.post("/api/feedback/grounding")
def api_grounding_feedback(req: GroundingFeedback, db: Session = Depends(get_session)):
    """Record a guardrail verdict a person disagreed with.

    The rows the guardrail gets wrong are the most valuable data this product
    produces, and every one of them was being thrown away. They are stored
    without a user id — this is about a statement and a CV excerpt, not about
    who applied where — and nothing reaches the eval set until it is reviewed
    by hand (evals/promote_feedback.py). A training set fed by unreviewed
    clicks learns whatever annoys people.
    """
    _require(req.statement, "statement")
    # Redact again rather than trust the client: this text is about to be
    # written to a database, and the caller may not be our own frontend.
    excerpt, _ = redact(req.cv_excerpt or "")
    statement, _ = redact(req.statement)

    row = GuardrailFeedback(
        statement=statement[:2000],
        cv_excerpt=excerpt[:4000],
        model_supported=1 if req.model_supported else 0,
        human_supported=1 if req.human_supported else 0,
        issue=(req.issue or "")[:1000],
    )
    db.add(row)
    db.commit()
    log_event("feedback.grounding", model_supported=req.model_supported,
              human_supported=req.human_supported)
    return {"ok": True}


@app.delete("/api/account")
def api_delete_account(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    """Delete the account and everything stored under it, for good.

    Offering an account that keeps someone's CV analyses without offering a way
    to remove them is half a feature. This deletes the tracker rows (including
    the stored analysis payloads, which contain CV-derived text), drops them
    from the search index, and then deletes the user, so a later login finds
    nothing rather than an empty shell.
    """
    rows = db.scalars(
        select(TrackedApplication).where(TrackedApplication.user_id == user.id)
    ).all()
    for row in rows:
        es_search.delete_app(row.id)  # best-effort; the DB is the source of truth
        db.delete(row)
    email = user.email
    db.delete(user)
    db.commit()
    log_event("account.deleted", applications=len(rows))
    logging.info("account deleted (%d applications)", len(rows))
    return {"ok": True, "deleted_applications": len(rows), "email": email}


@app.get("/api/privacy")
def api_privacy():
    """What this service keeps, for how long, and what it never sends onward.

    Machine-readable so the UI states the same policy the code implements,
    instead of a document that drifts away from it.
    """
    return {
        "sent_to_the_model": (
            "The job description, and your CV with contact details replaced by "
            "placeholders. Email addresses, phone numbers, ID numbers, street "
            "addresses and social links never leave this server."
        ),
        "stored_without_an_account": "Nothing. The tracker lives in your browser.",
        "stored_with_an_account": (
            "Your email, a hash of your password, and the analyses you chose to "
            "save to the tracker."
        ),
        "retention": "Saved analyses are kept until you delete them or your account.",
        "delete_everything": "DELETE /api/account",
        "third_parties": ["Groq (model inference)", "JailbreakAPI (input screening)"],
    }


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
    except CircuitOpen as exc:
        # The upstream is failing and we already know it, so say so quickly and
        # tell the caller when to come back rather than timing out again.
        log_event("request.short_circuited", reason=str(exc))
        raise HTTPException(
            status_code=503,
            detail="The AI service is having a bad minute. Try again shortly.",
            headers={"Retry-After": "30"},
        )
    except LLMError as exc:
        log_event("request.failed", error=str(exc)[:300])
        logging.warning("LLM error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _guard(result):
    return result
