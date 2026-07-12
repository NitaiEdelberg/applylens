"""SQLAlchemy engine, session, and models for optional accounts + cloud tracker.

Runs on SQLite locally with zero configuration (DATABASE_URL unset) and on
Postgres in production (set DATABASE_URL to the Supabase session-pooler URI).
Kept deliberately simple: synchronous SQLAlchemy with `def` FastAPI endpoints,
which FastAPI runs in a threadpool alongside the existing async LLM routes.
"""
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


def init_db() -> None:
    """Create tables if they don't exist. Safe to call repeatedly."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """FastAPI dependency yielding a Session that's always closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Create tables at import so tables exist regardless of how the app is started
# (uvicorn startup event, or a bare TestClient that doesn't run lifespan events).
init_db()
