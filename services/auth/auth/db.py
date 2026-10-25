"""Database access for the auth service: its own schema (``auth``) on the shared server.

``DATABASE_URL`` selects the server. PostgreSQL in Compose, SQLite for local runs and tests.
Tables are created at start-up; Alembic migrations replace this once the schema settles.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

SCHEMA = "auth"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginLog(Base):
    __tablename__ = "login_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(254))
    success: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./auth.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    if url == "sqlite://":  # in-memory, shared by every session (tests)
        from sqlalchemy.pool import StaticPool

        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False})


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
