"""Database access for the worklist service: its own schema (``worklist``).

A task row is created from a ``TaskRequested`` event and keeps that event, so the
completion can be sent back as its reply (same case, token, pathway and version).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from care_events import OutboxBase
from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = "worklist"


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 in UTC. SQLite returns stored times without a zone; they were written in UTC."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_event_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_json: Mapped[str] = mapped_column(Text)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    wait_id: Mapped[str] = mapped_column(String(120), index=True, default="")  # the engine's wait id
    pathway: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40), index=True)
    patient_id: Mapped[str] = mapped_column(String(64), default="")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)
    outputs: Mapped[list[dict[str, str]]] = mapped_column(JSON)  # [{name, type}] required to complete
    deadline_min: Mapped[float | None] = mapped_column(nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="task")  # task | undo (a compensation step)
    level: Mapped[int] = mapped_column(Integer, default=0)  # escalation level (ENG-06)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | claimed | done | cancelled
    assignee: Mapped[str | None] = mapped_column(String(254), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationRow(Base):
    """Escalation alerts and other messages for a role (email/SMS delivery is WRK-03)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(String(500))
    case_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./worklist.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    if url == "sqlite://":  # in-memory, shared by every session (tests)
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)
        OutboxBase.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
