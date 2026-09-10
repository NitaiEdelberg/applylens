"""SQLAlchemy engine, session, and models for optional accounts + cloud tracker.

Runs on SQLite locally with zero configuration (DATABASE_URL unset) and on
Postgres in production (set DATABASE_URL to the Supabase session-pooler URI).
Kept deliberately simple: synchronous SQLAlchemy with `def` FastAPI endpoints,
which FastAPI runs in a threadpool alongside the existing async LLM routes.
"""
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv()  # idempotent; picks up DATABASE_URL / JWT_SECRET from backend/.env


def _database_url() -> str:
    """Resolve the DB URL. Defaults to a local SQLite file so the app runs with
    no credential for local dev. Normalizes the legacy `postgres://` scheme
    (used by some providers) to the `postgresql://` SQLAlchemy expects.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///./applylens.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _database_url()

# check_same_thread is a SQLite-only quirk: FastAPI's threadpool touches the
# connection from worker threads, so disable the guard. Harmless/ignored on PG.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    applications = relationship(
        "TrackedApplication",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class GuardrailFeedback(Base):
    """A verdict a person disagreed with, kept so the eval set grows from use.

    The guardrail's mistakes are the most valuable data this product produces
    and it was throwing all of them away. Rows here are promoted into
    evals/dataset.jsonl by evals/promote_feedback.py after review — never
    automatically, because a training set fed by unreviewed clicks is a
    training set that learns whatever annoys people.

    Deliberately not linked to a user: this is about a statement and a CV
    excerpt, and attaching an identity to it would make it a record of who
    applied where.
    """

    __tablename__ = "guardrail_feedback"

    id = Column(Integer, primary_key=True)
    statement = Column(Text, nullable=False)
    # The CV, already redacted by services/redact.py before it ever reached the
    # model, truncated to the part that matters.
    cv_excerpt = Column(Text, nullable=False, default="")
    # What the guardrail said, and what the person said it should have been.
    model_supported = Column(Integer, nullable=False, default=0)
    human_supported = Column(Integer, nullable=False, default=0)
    issue = Column(Text, nullable=True)
    promoted = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TrackedApplication(Base):
    __tablename__ = "tracked_applications"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(500), nullable=False, default="Untitled role")
    company = Column(String(500), nullable=False, default="")
    status = Column(String(50), nullable=False, default="applied")
    score = Column(Integer, nullable=True)
    flagged = Column(Integer, nullable=False, default=0)
    # Full saved analysis blob (the same `result` the localStorage tracker keeps),
    # stored as a JSON string so re-opening a record needs no LLM call. Text keeps
    # it portable across SQLite and Postgres without a JSON-type dependency.
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="applications")


def init_db() -> bool:
    """Create tables if they don't exist. Never raises: a DB that's unreachable
    at startup (bad URL, paused Supabase, network) must NOT crash the whole API —
    the anonymous + LLM features don't need the DB. Returns True if the DB is
    reachable and tables are ready, False otherwise (accounts/tracker will then
    return a clean 503 until the DB is reachable).
    """
    try:
        Base.metadata.create_all(bind=engine)
        return True
    except Exception as exc:  # connection refused, auth, SSL, IPv6-only host, ...
        logging.warning(
            "Database unavailable at startup — accounts/tracker disabled until it is "
            "reachable (check DATABASE_URL uses the Supabase SESSION POOLER): %s",
            exc,
        )
        return False


# Reachability flag, refreshed on startup. SQLite (local/tests) always succeeds.
DB_READY = init_db()


def db_available() -> bool:
    """Best-effort liveness re-check so a DB that comes up after boot starts working."""
    global DB_READY
    if DB_READY:
        return True
    DB_READY = init_db()
    return DB_READY


def get_session():
    """FastAPI dependency yielding a Session that's always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
