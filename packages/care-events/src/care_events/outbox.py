"""Transactional outbox and duplicate-filtering inbox (reliability patterns, Category 4).

A service saves the events it must send in an ``outbox`` table *in the same transaction*
as its own change, so a crash can never keep one without the other (invariant I5). The
``OutboxRelay`` publishes saved rows afterwards and marks them sent; a crash between
publishing and marking only causes a duplicate, which consumers drop with their inbox.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from care_events.bus import Bus
from care_events.envelope import Event

log = logging.getLogger("care_events.outbox")


def _now() -> datetime:
    return datetime.now(UTC)


class OutboxBase(DeclarativeBase):
    """Tables shared by every service; each service creates them in its own schema."""


class OutboxRow(OutboxBase):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    event_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class InboxRow(OutboxBase):
    """Ids of events this service has already handled (duplicate filter for consumers)."""

    __tablename__ = "inbox"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    handled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def add_to_outbox(session: Session, *events: Event) -> None:
    """Queue events for publishing; they leave only if the caller's transaction commits."""
    for e in events:
        session.add(OutboxRow(event_id=e.event_id, event_json=e.to_json()))


def first_time(session: Session, event_id: str) -> bool:
    """Record ``event_id`` as handled; False if it already was (then the caller does nothing).

    Must run inside the caller's transaction, so the record and the change commit together.
    """
    if session.get(InboxRow, event_id) is not None:
        return False
    session.add(InboxRow(event_id=event_id))
    try:
        session.flush()
    except IntegrityError:  # a concurrent copy got there first
        session.rollback()
        return False
    return True


class OutboxRelay:
    """Publishes committed outbox rows in order, at least once."""

    def __init__(self, sessions: sessionmaker[Session], bus: Bus, interval_s: float = 0.05) -> None:
        self.sessions = sessions
        self.bus = bus
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.before_mark: Callable[[Event], None] | None = None  # fault injection in tests

    def flush(self, limit: int = 500) -> int:
        """Publish what is waiting now; returns how many events were sent."""
        with self._lock, self.sessions() as s:
            rows = s.scalars(
                select(OutboxRow).where(OutboxRow.published_at.is_(None)).order_by(OutboxRow.id).limit(limit)
            ).all()
            for row in rows:
                event = Event.from_json(row.event_json)
                self.bus.publish(event)
                if self.before_mark:
                    self.before_mark(event)
                row.published_at = _now()
                s.commit()
            return len(rows)

    def notify(self) -> None:
        self._wake.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.flush()
            except Exception:
                log.exception("outbox relay failed; retrying")
            self._wake.wait(self.interval_s)
            self._wake.clear()
