"""worklist service: tasks for people (WRK-01).

Feature IDs: C1-04 (later also notifications C2-07 and case summaries C1-05/C1-07).
It consumes ``TaskRequested.worklist``: each becomes a task for the role the designer
drew. Nurses and doctors see the open tasks for their role, claim one, and complete it
with the outputs the pathway needs; the completion goes back to the engine as
``TaskCompleted`` through the outbox. A failed or finished case cancels its open tasks.

Sprint 4: ``TaskReassigned`` moves an overdue task to the next role of the escalation
chain (ENG-06); ``NotificationRequested`` becomes an alert for a role; ``CancelRequested``
cancels a task; ``CompensateRequested`` creates an "Undo" task whose completion answers
``Compensated`` (ENG-08).

Sprint 7: the monitor (``worklist.monitor``) records every case's history for admins and
managers (MON-01) and computes the manager's dashboard (MON-02); every notification is
also sent by email or SMS to the role's alert contacts (WRK-03, ``worklist.alerts``).
"""

import os
import re
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from care_events import Bus, Event, OutboxRelay, add_to_outbox, first_time
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from service_metrics import case_context, instrument
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from worklist.alerts import (
    AlertContactRow,
    AlertSender,
    Channel,
    DeliveryRow,
    channels_from_env,
    contact_out,
    delivery_out,
    queue_deliveries,
)
from worklist.db import Database, NotificationRow, OverrideRow, TaskRow, iso, make_engine, now
from worklist.monitor import CaseEventRow, CaseSummaryRow, Monitor, dashboard, event_out, summary_out


class CompleteIn(BaseModel):
    outputs: dict[str, Any]
    reason: str | None = None  # WRK-02: required when the decision differs from the suggestion


class FailIn(BaseModel):
    reason: str


EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PHONE = r"^\+[1-9][0-9]{6,14}$"  # E.164


class ContactIn(BaseModel):
    role: Literal["charge_nurse", "manager", "nurse", "doctor", "admin"]
    channel: Literal["email", "sms"]
    address: str = Field(max_length=254)
    name: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def address_fits_channel(self) -> "ContactIn":
        pattern = EMAIL if self.channel == "email" else PHONE
        if not re.match(pattern, self.address.strip()):
            kind = "an email address" if self.channel == "email" else "a phone number like +4915112345678"
            raise ValueError(f"address must be {kind}")
        self.address = self.address.strip()
        return self


class ContactPatch(BaseModel):
    active: bool


MIN_REASON = 5


def type_ok(value: Any, var_type: str) -> bool:
    if var_type == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if var_type == "int":
        return isinstance(value, int)
    if var_type == "float":
        return isinstance(value, int | float)
    return isinstance(value, str) and value.strip() != ""


def task_out(t: TaskRow) -> dict[str, Any]:
    return {
        "id": t.id,
        "case_id": t.case_id,
        "pathway": t.pathway,
        "version": t.version,
        "node": t.node,
        "label": t.label,
        "role": t.role,
        "patient_id": t.patient_id,
        "inputs": t.inputs,
        "outputs": t.outputs,
        "deadline_min": t.deadline_min,
        "due_at": iso(t.due_at),
        "kind": t.kind,
        "level": t.level,
        "override": t.override,
        "status": t.status,
        "assignee": t.assignee,
        "result": t.result,
        "created_at": iso(t.created_at),
        "claimed_at": iso(t.claimed_at),
        "completed_at": iso(t.completed_at),
    }


# ---- event consumer -------------------------------------------------------------------


class Consumer:
    BINDINGS = [
        "TaskRequested.worklist",
        "CompensateRequested.worklist",
        "CancelRequested.worklist",
        "TaskReassigned",
        "NotificationRequested",
        "CaseFailed",
        "CaseCancelled",
        "CaseCompensated",
    ]

    def __init__(self, db: Database, on_alert: Callable[[], None] = lambda: None) -> None:
        self.db = db
        self.on_alert = on_alert

    def on_event(self, event: Event) -> None:
        with case_context(event.case_id):  # every log line carries the case id (C4-06)
            self._handle(event)

    def _handle(self, event: Event) -> None:
        with self.db.sessions.begin() as s:
            if not first_time(s, event.event_id):
                return  # duplicate delivery
            handler = {
                "TaskRequested": self._requested,
                "CompensateRequested": self._requested,
                "TaskReassigned": self._reassigned,
                "CancelRequested": self._cancel_task,
                "NotificationRequested": self._notify,
            }.get(event.type, self._case_ended)
            handler(s, event)
        if event.type == "NotificationRequested":
            self.on_alert()  # after the commit: wake the sender for the new deliveries

    def _requested(self, s: Session, e: Event) -> None:
        s.add(self._task_from(e))

    def _reassigned(self, s: Session, e: Event) -> None:
        t = self._task_for(s, e)
        if t is not None and t.status in ("open", "claimed") and e.payload.get("level", 0) > t.level:
            t.role, t.level, t.status, t.assignee = e.payload["role"], e.payload["level"], "open", None
            t.due_at = _parse(e.payload.get("due_at"))

    def _cancel_task(self, s: Session, e: Event) -> None:
        t = self._task_for(s, e)
        if t is not None and t.status in ("open", "claimed"):
            t.status = "cancelled"

    def _notify(self, s: Session, e: Event) -> None:
        p = e.payload
        n = NotificationRow(
            event_id=e.event_id, role=p["role"], message=p["message"], case_id=e.case_id or ""
        )
        s.add(n)
        queue_deliveries(s, n)  # WRK-03, same transaction

    def _case_ended(self, s: Session, e: Event) -> None:
        for t in s.scalars(select(TaskRow).where(TaskRow.case_id == e.case_id, TaskRow.kind == "task")):
            if t.status in ("open", "claimed"):
                t.status = "cancelled"

    @staticmethod
    def _task_for(s: Session, e: Event) -> TaskRow | None:
        q = select(TaskRow).where(TaskRow.case_id == e.case_id, TaskRow.wait_id == e.payload.get("task_id"))
        return s.scalars(q).first()

    @staticmethod
    def _task_from(e: Event) -> TaskRow:
        p = e.payload
        deadline = p.get("deadline") or {}
        return TaskRow(
            request_event_id=e.event_id,
            request_json=e.to_json(),
            case_id=e.case_id or "",
            wait_id=e.token_id or "",
            pathway=e.pathway or "",
            version=e.version or 0,
            node=p.get("node", ""),
            label=p.get("label", ""),
            role=p.get("role") or "",
            patient_id=str(p.get("patient_id") or ""),
            inputs=p.get("inputs", {}),
            outputs=p.get("outputs", []),
            deadline_min=deadline.get("minutes"),
            due_at=_parse(p.get("due_at")),
            kind="undo" if e.type == "CompensateRequested" else "task",
            override=p.get("override"),
        )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# ---- REST ---------------------------------------------------------------------------------

router = APIRouter()


def session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    yield from db.session()


SessionDep = Annotated[Session, Depends(session)]
Email = Annotated[str, Header(alias="x-user-email")]
Role = Annotated[str, Header(alias="x-user-role")]


def get_task(s: Session, task_id: int, role: str) -> TaskRow:
    t = s.get(TaskRow, task_id)
    if t is None or t.role != role:  # another role's task is invisible, not forbidden
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return t


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "worklist"}


@router.get("/tasks")
def list_tasks(s: SessionDep, email: Email, role: Role, include_done: bool = False) -> list[dict[str, Any]]:
    """WRK-01: open tasks for my role, plus the ones I claimed (and, if asked, my finished ones)."""
    mine = TaskRow.assignee == email
    wanted = [TaskRow.status == "open", (TaskRow.status == "claimed") & mine]
    if include_done:
        wanted.append((TaskRow.status == "done") & mine)
    q = select(TaskRow).where(TaskRow.role == role, or_(*wanted)).order_by(TaskRow.created_at, TaskRow.id)
    return [task_out(t) for t in s.scalars(q)]


@router.get("/notifications")
def notifications(s: SessionDep, role: Role, limit: int = 50) -> list[dict[str, Any]]:
    """Alerts for my role (escalations; for managers, tasks still open after every level)."""
    q = select(NotificationRow).order_by(NotificationRow.id.desc()).limit(min(limit, 200))
    if role != "admin":
        q = q.where(NotificationRow.role == role)
    return [
        {
            "id": n.id,
            "role": n.role,
            "message": n.message,
            "case_id": n.case_id,
            "created_at": iso(n.created_at),
        }
        for n in s.scalars(q)
    ]


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, s: SessionDep, email: Email, role: Role) -> dict[str, Any]:
    t = get_task(s, task_id, role)
    if t.status == "claimed" and t.assignee == email:
        return task_out(t)
    if t.status != "open":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"task is {t.status}" + (f" by {t.assignee}" if t.assignee else "")
        )
    t.status, t.assignee, t.claimed_at = "claimed", email, now()
    s.commit()
    return task_out(t)


@router.post("/tasks/{task_id}/release")
def release(task_id: int, s: SessionDep, email: Email, role: Role) -> dict[str, Any]:
    t = get_task(s, task_id, role)
    if t.status != "claimed" or t.assignee != email:
        raise HTTPException(status.HTTP_409_CONFLICT, "only the person who claimed a task can release it")
    t.status, t.assignee, t.claimed_at = "open", None, None
    s.commit()
    return task_out(t)


@router.post("/tasks/{task_id}/complete")
def complete(
    task_id: int, body: CompleteIn, request: Request, s: SessionDep, email: Email, role: Role
) -> dict[str, Any]:
    """WRK-01: complete a claimed task with exactly the outputs the pathway declares."""
    t = get_task(s, task_id, role)
    if t.status != "claimed" or t.assignee != email:
        raise HTTPException(status.HTTP_409_CONFLICT, "claim the task before completing it")
    bad = [o["name"] for o in t.outputs if not type_ok(body.outputs.get(o["name"]), o["type"])]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"missing or invalid outputs: {', '.join(bad)}"
        )
    outputs = {o["name"]: body.outputs[o["name"]] for o in t.outputs}
    changed = check_override(s, t, outputs, body.reason, email)
    request_event = Event.from_json(t.request_json)
    if t.kind == "undo":  # a compensation step answers Compensated (ENG-08)
        add_to_outbox(s, request_event.reply("Compensated", {"ok": True, "completed_by": email}))
    else:
        payload: dict[str, Any] = {"outputs": outputs, "completed_by": email}
        if changed:
            payload["override"] = changed
        add_to_outbox(s, request_event.reply("TaskCompleted", payload))
    t.status, t.result, t.completed_at = "done", outputs, now()
    s.commit()
    request.app.state.relay.notify()
    return task_out(t)


def check_override(
    s: Session, t: TaskRow, outputs: dict[str, Any], reason: str | None, email: str
) -> dict[str, Any] | None:
    """WRK-02: a decision that differs from the suggestion needs a reason, which is logged."""
    if not t.override:
        return None
    suggested, decided = t.inputs.get(t.override["suggested"]), outputs.get(t.override["decided"])
    if decided == suggested:
        return None
    if reason is None or len(reason.strip()) < MIN_REASON:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"changing the suggested {t.override['suggested']} ({suggested}) to {decided} needs a reason",
        )
    s.add(
        OverrideRow(
            task_id=t.id,
            case_id=t.case_id,
            patient_id=t.patient_id,
            node=t.node,
            suggested=str(suggested),
            decided=str(decided),
            reason=reason.strip(),
            by=email,
        )
    )
    return {"suggested": suggested, "decided": decided, "reason": reason.strip()}


@router.post("/tasks/{task_id}/fail")
def fail(
    task_id: int, body: FailIn, request: Request, s: SessionDep, email: Email, role: Role
) -> dict[str, Any]:
    """Report that a claimed task cannot be done (e.g. the transfer is impossible): the
    engine then takes the fallback branch or undoes the finished steps (ENG-08)."""
    t = get_task(s, task_id, role)
    if t.status != "claimed" or t.assignee != email:
        raise HTTPException(status.HTTP_409_CONFLICT, "claim the task before reporting a problem")
    if len(body.reason.strip()) < MIN_REASON:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "say what went wrong")
    request_event = Event.from_json(t.request_json)
    if t.kind == "undo":
        add_to_outbox(
            s, request_event.reply("Compensated", {"ok": False, "reason": body.reason, "by": email})
        )
    else:
        add_to_outbox(
            s, request_event.reply("TaskFailed", {"reason": body.reason, "temporary": False, "by": email})
        )
    t.status, t.result, t.completed_at = "failed", {"problem": body.reason.strip()}, now()
    s.commit()
    request.app.state.relay.notify()
    return task_out(t)


@router.get("/overrides")
def overrides(s: SessionDep, limit: int = 100) -> list[dict[str, Any]]:
    """WRK-02 audit: who changed which suggestion, to what, and why (managers, admins)."""
    q = select(OverrideRow).order_by(OverrideRow.id.desc()).limit(min(limit, 500))
    return [
        {
            "id": o.id,
            "task_id": o.task_id,
            "case_id": o.case_id,
            "patient_id": o.patient_id,
            "node": o.node,
            "suggested": o.suggested,
            "decided": o.decided,
            "reason": o.reason,
            "by": o.by,
            "at": iso(o.at),
        }
        for o in s.scalars(q)
    ]


@router.get("/cases")
def cases(
    s: SessionDep,
    status_: Annotated[str | None, Query(alias="status")] = None,
    pathway: str | None = None,
    patient: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    """MON-01: every case the monitor has seen, newest first, filtered if asked."""
    q = select(CaseSummaryRow).order_by(CaseSummaryRow.started_at.desc()).limit(limit)
    if status_:
        q = q.where(CaseSummaryRow.status == status_)
    if pathway:
        q = q.where(CaseSummaryRow.pathway == pathway)
    if patient:
        q = q.where(CaseSummaryRow.patient_id == patient.strip().upper())
    return [summary_out(c) for c in s.scalars(q)]


@router.get("/cases/{case_id}")
def case_history(case_id: str, s: SessionDep) -> dict[str, Any]:
    """MON-01: a case's full history, and the patient's other cases (the journey across
    the chained pathways: Triage, Assessment, Visit)."""
    c = s.get(CaseSummaryRow, case_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    events = s.scalars(
        select(CaseEventRow).where(CaseEventRow.case_id == case_id).order_by(CaseEventRow.at, CaseEventRow.id)
    )
    journey: Iterable[CaseSummaryRow] = (
        s.scalars(
            select(CaseSummaryRow)
            .where(CaseSummaryRow.patient_id == c.patient_id)
            .order_by(CaseSummaryRow.started_at)
        )
        if c.patient_id
        else []
    )
    return {
        **summary_out(c),
        "history": [event_out(e) for e in events],
        "journey": [summary_out(j) for j in journey],
    }


@router.get("/dashboard")
def manager_dashboard(s: SessionDep, hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24) -> dict[str, Any]:
    """MON-02: active cases, queues, waits and missed deadlines."""
    return dashboard(s, hours=hours)


def _count(db: Database, row: Any, status_value: str) -> float:
    with db.sessions() as s:
        return float(s.scalar(select(func.count()).select_from(row).where(row.status == status_value)) or 0)


# ---- WRK-03: alert contacts (admins) and deliveries ----------------------------------------


@router.get("/alert-contacts")
def contacts(s: SessionDep) -> list[dict[str, Any]]:
    q = select(AlertContactRow).order_by(AlertContactRow.role, AlertContactRow.id)
    return [contact_out(c) for c in s.scalars(q)]


@router.post("/alert-contacts", status_code=status.HTTP_201_CREATED)
def add_contact(body: ContactIn, s: SessionDep) -> dict[str, Any]:
    c = AlertContactRow(role=body.role, channel=body.channel, address=body.address, name=body.name.strip())
    s.add(c)
    s.commit()
    return contact_out(c)


@router.patch("/alert-contacts/{contact_id}")
def set_contact(contact_id: int, body: ContactPatch, s: SessionDep) -> dict[str, Any]:
    c = s.get(AlertContactRow, contact_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    c.active = body.active
    s.commit()
    return contact_out(c)


@router.get("/deliveries")
def deliveries(s: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict[str, Any]]:
    """WRK-03: what was sent to whom, and what failed (admins, managers)."""
    q = select(DeliveryRow).order_by(DeliveryRow.id.desc()).limit(limit)
    return [delivery_out(d) for d in s.scalars(q)]


def create_app(
    db: Database | None = None, bus: Bus | None = None, channels: dict[str, Channel] | None = None
) -> FastAPI:
    """Build the service; tests and the dev stack pass a database and a shared bus."""
    database = db or Database(make_engine())
    owns_bus = bus is None
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    relay = OutboxRelay(database.sessions, the_bus)
    sender = AlertSender(database.sessions, channels or channels_from_env())
    consumer = Consumer(database, on_alert=sender.notify)
    the_bus.subscribe("worklist", Consumer.BINDINGS, consumer.on_event)
    monitor = Monitor(database)
    the_bus.subscribe("monitor", Monitor.BINDINGS, monitor.on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        relay.start()
        sender.start()
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()
        sender.stop()
        relay.stop()

    app = FastAPI(title="AdaptiveCare worklist", version="0.3.0", lifespan=lifespan)
    app.state.metrics = metrics = instrument(app, "worklist")
    metrics.gauge(
        "worklist_open_tasks", "Tasks waiting for a person.", lambda: _count(database, TaskRow, "open")
    )
    metrics.gauge(
        "worklist_alerts_pending", "Alerts not yet sent.", lambda: _count(database, DeliveryRow, "pending")
    )
    app.state.db, app.state.relay, app.state.consumer = database, relay, consumer
    app.state.monitor, app.state.sender = monitor, sender
    app.include_router(router)
    return app
