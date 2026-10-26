"""auth service: users, roles, login, tokens, login log.

Feature IDs: C1-01, C4-03. Stories: AUTH-01 (admin creates users with a role),
AUTH-02 (login returns a token that expires). The gateway enforces roles on every
route (AUTH-03); this service checks the admin role again on /users as defence in depth.
"""

import os
from collections.abc import Iterator
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from service_metrics import instrument
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.db import Database, LoginLog, User, make_engine
from auth.security import ROLES, check_password, hash_password, make_token, read_token


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=72)  # bcrypt reads at most 72 bytes
    role: str

    @field_validator("role")
    @classmethod
    def known_role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        return v


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)

    @field_validator("role")
    @classmethod
    def known_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        return v


def user_out(u: User) -> dict[str, Any]:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.active}


def seed_admin(db: Database) -> None:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD when there are no users yet."""
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return
    with db.sessions() as s:
        if s.scalar(select(User.id).limit(1)) is None:
            s.add(
                User(
                    name="Administrator",
                    email=email.lower(),
                    password_hash=hash_password(password),
                    role="admin",
                )
            )
            s.commit()


# The OAuth 2 token type name, not a secret.
TOKEN_TYPE = "bearer"  # noqa: S105  # nosec B105
router = APIRouter()


def session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    yield from db.session()


SessionDep = Annotated[Session, Depends(session)]


def current_claims(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        return read_token(authorization.removeprefix("Bearer "), "access")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from exc


Claims = Annotated[dict[str, Any], Depends(current_claims)]


def admin(claims: Claims) -> dict[str, Any]:
    if claims["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return claims


Admin = Annotated[dict[str, Any], Depends(admin)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auth"}


@router.post("/auth/login")
def login(body: LoginIn, s: SessionDep) -> dict[str, Any]:
    email = body.email.strip().lower()
    user = s.scalar(select(User).where(User.email == email))
    ok = user is not None and user.active and check_password(body.password, user.password_hash)
    s.add(LoginLog(user_id=user.id if user else None, email=email, success=ok))
    s.commit()
    if not ok or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
    return {
        "access_token": make_token(user.id, user.email, user.role, "access"),
        "refresh_token": make_token(user.id, user.email, user.role, "refresh"),
        "token_type": TOKEN_TYPE,
        "user": user_out(user),
    }


@router.post("/auth/refresh")
def refresh(body: RefreshIn, s: SessionDep) -> dict[str, Any]:
    try:
        claims = read_token(body.refresh_token, "refresh")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired refresh token") from exc
    user = s.get(User, int(claims["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user is no longer active")
    # The role is read again, so a role change takes effect at the next refresh.
    return {"access_token": make_token(user.id, user.email, user.role, "access"), "token_type": TOKEN_TYPE}


@router.get("/auth/me")
def me(claims: Claims, s: SessionDep) -> dict[str, Any]:
    user = s.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user_out(user)


@router.get("/users")
def list_users(_: Admin, s: SessionDep) -> list[dict[str, Any]]:
    return [user_out(u) for u in s.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, _: Admin, s: SessionDep) -> dict[str, Any]:
    email = body.email.strip().lower()
    if s.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a user with this email exists")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password), role=body.role)
    s.add(user)
    s.commit()
    return user_out(user)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, claims: Admin, s: SessionDep) -> dict[str, Any]:
    user = s.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.id == int(claims["sub"]) and (body.active is False or body.role not in (None, "admin")):
        raise HTTPException(status.HTTP_409_CONFLICT, "admins cannot demote or deactivate themselves")
    for field in ("name", "role", "active"):
        if (value := getattr(body, field)) is not None:
            setattr(user, field, value)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    s.commit()
    return user_out(user)


def create_app(db: Database | None = None) -> FastAPI:
    """Build the service; tests pass an in-memory database."""
    database = db or Database(make_engine())
    seed_admin(database)
    app = FastAPI(title="AdaptiveCare auth", version="0.2.0")
    app.state.metrics = instrument(app, "auth")
    app.state.db = database
    app.include_router(router)
    return app
