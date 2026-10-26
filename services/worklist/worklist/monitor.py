"""Case monitor (MON-01, MON-02): case summaries and every case's history, from the bus.

The worklist's ``monitor`` queue is bound to ``#``: it sees every event that leaves a
service, so it can keep, for each case, a summary (pathway, patient, status, times) and
the full timeline of requests, completions, failures, escalations and undo steps. The
record outlives the engine container, which is stopped once its version is retired
(decision 0007). Duplicate deliveries are dropped by the event id, which is unique in
``case_events``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from care_events import Event
from sqlalchemy import JSON, DateTime, Integer, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from worklist.db import Base, Database, TaskRow, aware, iso, now

END_STATUS = {
    "CaseCompleted": "completed",
    "CaseFailed": "failed",
    "CaseCompensated": "compensated",
    "CaseCancelled": "cancelled",
}
# Payload fields worth keeping in the timeline (the rest stays in the engine's own log).
KEPT = (
    "node", "label", "role", "service", "kind", "outputs", "completed_by", "by", "reason", "temporary",
    "override", "level", "due_at", "message", "ok", "action", "end", "trigger", "probabilities",
)  # fmt: skip


class CaseSummaryRow(Base):
    __tablename__ = "case_summaries"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pathway: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    patient_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(20), index=True, default="running")
    reason: Mapped[str] = mapped_column(String(500), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events: Mapped[int] = mapped_column(Integer, default=0)


class CaseEventRow(Base):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(64))
    token_id: Mapped[str] = mapped_column(String(120), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)


class Monitor:
    BINDINGS = ["#"]

    def __init__(self, db: Database) -> None:
        self.db = db

    def on_event(self, event: Event) -> None:
        if not event.case_id:
            return  # e.g. PatientRegistered: not yet a case
        try:
            with self.db.sessions.begin() as s:
                if s.scalars(select(CaseEventRow.id).where(CaseEventRow.event_id == event.event_id)).first():
                    return  # duplicate delivery
                self._record(s, event)
        except IntegrityError:
            return  # a concurrent copy of the same event was recorded first

    @staticmethod
    def _record(s: Session, e: Event) -> None:
        at = datetime.fromisoformat(e.timestamp)
        detail = {k: e.payload[k] for k in KEPT if k in e.payload}
        s.add(CaseEventRow(event_id=e.event_id, case_id=e.case_id, type=e.type, token_id=e.token_id or "",
                           at=at, detail=detail))  # fmt: skip
        Monitor._summarise(s, e, at)

    @staticmethod
    def _summarise(s: Session, e: Event, at: datetime) -> None:
        """Open the case's summary on its first event; track its status and end."""
        summary = s.get(CaseSummaryRow, e.case_id)
        if summary is None:  # usually CaseStarted; any first event of a case opens its summary
            summary = CaseSummaryRow(
                case_id=e.case_id, pathway=e.pathway or "", version=e.version or 0, started_at=at, events=0
            )
            s.add(summary)
        summary.events += 1
        if e.type == "CaseStarted":
            summary.patient_id, summary.started_at = str(e.payload.get("patient_id") or ""), at
        elif e.type in END_STATUS:
            summary.status, summary.ended_at = END_STATUS[e.type], at
            summary.reason = str(e.payload.get("reason") or "")[:500]


def summary_out(c: CaseSummaryRow) -> dict[str, Any]:
    return {
        "case_id": c.case_id,
        "pathway": c.pathway,
        "version": c.version,
        "patient_id": c.patient_id,
        "status": c.status,
        "reason": c.reason,
        "started_at": iso(c.started_at),
        "ended_at": iso(c.ended_at),
        "events": c.events,
    }


def event_out(e: CaseEventRow) -> dict[str, Any]:
    return {"id": e.id, "type": e.type, "token_id": e.token_id, "at": iso(e.at), "detail": e.detail}


# ---- MON-02: the manager's dashboard --------------------------------------------------------


def _minutes(a: datetime, b: datetime) -> float:
    return (aware(b) - aware(a)).total_seconds() / 60


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def _wait_stats(tasks: list[TaskRow]) -> dict[str, dict[str, Any]]:
    """Per role: how long finished-or-claimed tasks waited before someone took them."""
    waits: dict[str, list[float]] = {}
    for t in tasks:
        if t.claimed_at is not None:
            waits.setdefault(t.role, []).append(_minutes(t.created_at, t.claimed_at))
    return {
        role: {"claimed": len(w), "mean_min": round(sum(w) / len(w), 1), "p90_min": _percentile(w, 0.9)}
        for role, w in sorted(waits.items())
    }


def _deadlines(tasks: list[TaskRow], at: datetime) -> dict[str, Any]:
    """Tasks with a deadline: how many were (or are) late, and how many escalated."""
    timed = [t for t in tasks if t.due_at is not None and t.status != "cancelled"]
    missed = [t for t in timed if aware(t.completed_at or at) > aware(t.due_at)]  # type: ignore[arg-type]
    return {
        "with_deadline": len(timed),
        "missed": len(missed),
        "missed_rate": round(len(missed) / len(timed), 3) if timed else None,
        "escalated": sum(1 for t in tasks if t.level > 0),
    }


def dashboard(s: Session, at: datetime | None = None, hours: int = 24) -> dict[str, Any]:
    """MON-02: active cases, waits and missed deadlines over the last ``hours``."""
    at = at or now()
    since = at - timedelta(hours=hours)
    active = s.execute(
        select(CaseSummaryRow.pathway, func.count())
        .where(CaseSummaryRow.status == "running")
        .group_by(CaseSummaryRow.pathway)
    ).all()
    ended = s.execute(
        select(CaseSummaryRow.status, func.count())
        .where(CaseSummaryRow.ended_at >= since)
        .group_by(CaseSummaryRow.status)
    ).all()
    recent = list(s.scalars(select(TaskRow).where(TaskRow.created_at >= since, TaskRow.kind == "task")))
    open_now = list(s.scalars(select(TaskRow).where(TaskRow.status.in_(("open", "claimed")))))
    queues: dict[str, dict[str, Any]] = {}
    for t in open_now:
        q = queues.setdefault(t.role, {"open": 0, "oldest_min": 0.0, "overdue": 0})
        q["open"] += 1
        q["oldest_min"] = max(q["oldest_min"], round(_minutes(t.created_at, at), 1))
        q["overdue"] += int(t.due_at is not None and aware(t.due_at) < at)
    return {
        "at": iso(at),
        "hours": hours,
        "active_cases": {pathway: n for pathway, n in active},
        "ended_cases": {status: n for status, n in ended},
        "queues": dict(sorted(queues.items())),
        "waits": _wait_stats(recent),
        "deadlines": _deadlines(recent, at),
    }
