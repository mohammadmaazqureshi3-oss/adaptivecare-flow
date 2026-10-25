"""Password hashing (bcrypt) and tokens (JWT, HS256). NFR-SEC-01.

Access tokens expire after 15 minutes, refresh tokens after 8 hours. The gateway
checks access tokens with the same secret; a refresh token is accepted only by
``POST /auth/refresh``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

ROLES = ("admin", "designer", "nurse", "doctor", "manager")
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(hours=8)
ALGORITHM = "HS256"


def secret() -> str:
    value = os.environ.get("JWT_SECRET")
    if not value:
        raise RuntimeError("JWT_SECRET is not set")
    return value


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def make_token(user_id: int, email: str, role: str, kind: str, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    ttl = ACCESS_TTL if kind == "access" else REFRESH_TTL
    claims = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": kind,
        "iat": issued,
        "exp": issued + ttl,
    }
    return jwt.encode(claims, secret(), algorithm=ALGORITHM)


def read_token(token: str, kind: str) -> dict[str, Any]:
    """Decode and check a token. Raises ``jwt.InvalidTokenError`` if expired, forged or the wrong kind."""
    claims: dict[str, Any] = jwt.decode(token, secret(), algorithms=[ALGORITHM])
    if claims.get("type") != kind:
        raise jwt.InvalidTokenError(f"expected a {kind} token")
    return claims
