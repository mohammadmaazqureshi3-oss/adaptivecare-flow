"""Database access for the deployer service: its own schema (``deployer``)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

from care_events import OutboxBase
from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = "deployer"


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 in UTC. SQLite returns stored times without a zone; they were written in UTC."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class DeploymentRow(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer, index=True)
    pathway: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    container: Mapped[str] = mapped_column(String(100))
    queue: Mapped[str] = mapped_column(String(100))
    schema_name: Mapped[str] = mapped_column(String(100))
    config_json: Mapped[str] = mapped_column(Text)  # the generated PSM, kept for the report and restarts
    status: Mapped[str] = mapped_column(String(20))  # starting | running | failed | draining | retired
    error: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[str] = mapped_column(String(254), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    healthy_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./deployer.db")
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
        OutboxBase.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
