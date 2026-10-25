"""Database access for the simulator service: scenarios and results (C1-06), schema ``simulator``."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = "simulator"


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    """One simulation or staffing-advice run: its scenario in, its result out."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer, index=True)
    pathway: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # simulate | advise
    scenario: Mapped[dict[str, Any]] = mapped_column(JSON)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./simulator.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    if url == "sqlite://":
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
