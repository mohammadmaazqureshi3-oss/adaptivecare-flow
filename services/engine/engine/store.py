"""The engine's event store: its own schema per deployed version (e.g. ``engine_triage_v1``).

``case_events`` keeps every inbound event a case accepted, in order: it is the case's
source of truth, and replaying it rebuilds the case (I3). Outbound events go to the
shared ``outbox`` table in the same transaction (I5). ``cases`` is a summary for lists.
``timers`` holds due times (deadlines, retry delays, timer nodes) so they survive a
restart; ``snapshots`` saves a case every 50 events so loading replays only the tail.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

from care_events import OutboxBase
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CaseEventRow(Base):
    __tablename__ = "case_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)  # duplicate filter (I1)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    event_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaseRow(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TimerRow(Base):
    __tablename__ = "timers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # the TimerScheduled event id
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_json: Mapped[str] = mapped_column(Text)
    fired: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upto_seq: Mapped[int] = mapped_column(Integer)  # last case_events.seq included
    state_json: Mapped[str] = mapped_column(Text)


class StateRow(Base):
    """Engine-wide settings that survive restarts, e.g. draining = "1" (DEP-02)."""

    __tablename__ = "engine_state"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


def make_engine(url: str | None = None, schema: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./engine.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        schema = schema or os.environ.get("ENGINE_SCHEMA", "engine")
        return create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    if url == "sqlite://":
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_wal(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        # Readers do not block the single writer; enough for local runs and tests.
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return engine


class Store:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)
        OutboxBase.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
