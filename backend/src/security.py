"""Password hashing (bcrypt via passlib) and JWT issue/verify helpers.

Isolated from the routes so both auth endpoints and the current_user dependency
share one implementation. JWT is signed with JWT_SECRET (a dev fallback keeps
local/tests working with no configuration).
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext

# Dev fallback keeps local + tests running with no config. MUST be overridden in
# prod via the JWT_SECRET env var (a leaked default would let anyone mint tokens).
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=30)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    # bcrypt only hashes the first 72 bytes; truncate explicitly so longer inputs
    # don't raise on newer backends and behave consistently on verify.
    return _pwd.hash(password[:72])


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd.verify(password[:72], password_hash)
    except Exception:  # noqa: BLE001 — malformed hash should never 500 a login
        return False


def create_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # PyJWT<2 returns bytes; normalize to str for a stable JSON response.
    return token.decode("utf-8") if isinstance(token, bytes) else token


def decode_token(token: str) -> Optional[int]:
    """Return the user id from a valid token, or None if missing/invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:  # noqa: BLE001 — any decode failure is just "not authed"
        return None
