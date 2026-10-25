"""worklist service: tasks for people (WRK-01).

Feature IDs: C1-04 (later also notifications C2-07 and case summaries C1-05/C1-07).
It consumes ``TaskRequested.worklist``: each becomes a task for the role the designer
drew. Nurses and doctors see the open tasks for their role, claim one, and complete it
with the outputs the pathway needs; the completion goes back to the engine as
``TaskCompleted`` through the outbox. A failed or finished case cancels its open tasks.
"""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from care_events import Bus, Event, OutboxRelay, add_to_outbox, first_time
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from worklist.db import Database, TaskRow, iso, make_engine, now


class CompleteIn(BaseModel):
    outputs: dict[str, Any]


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
        "status": t.status,
        "assignee": t.assignee,
        "result": t.result,
        "created_at": iso(t.created_at),
        "completed_at": iso(t.completed_at),
    }


# ---- event consumer -------------------------------------------------------------------


class Consumer:
    def __init__(self, db: Database) -> None:
        self.db = db

    def on_event(self, event: Event) -> None:
        with self.db.sessions.begin() as s:
            if not first_time(s, event.event_id):
                return  # duplicate delivery
            if event.type == "TaskRequested":
                s.add(self._task_from(event))
            elif event.type in ("CaseFailed", "CaseCancelled", "CaseCompensated"):
                for t in s.scalars(select(TaskRow).where(TaskRow.case_id == event.case_id)):
                    if t.status in ("open", "claimed"):
                        t.status = "cancelled"

    @staticmethod
    def _task_from(e: Event) -> TaskRow:
        p = e.payload
        deadline = p.get("deadline") or {}
        return TaskRow(
            request_event_id=e.event_id,
            request_json=e.to_json(),
            case_id=e.case_id or "",
            pathway=e.pathway or "",
            version=e.version or 0,
            node=p.get("node", ""),
            label=p.get("label", ""),
            role=p.get("role") or "",
            patient_id=str(p.get("patient_id") or ""),
            inputs=p.get("inputs", {}),
            outputs=p.get("outputs", []),
            deadline_min=deadline.get("minutes"),
        )


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


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, s: SessionDep, email: Email, role: Role) -> dict[str, Any]:
    t = get_task(s, task_id, role)
    if t.status == "claimed" and t.assignee == email:
        return task_out(t)
    if t.status != "open":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"task is {t.status}" + (f" by {t.assignee}" if t.assignee else "")
        )
    t.status, t.assignee = "claimed", email
    s.commit()
    return task_out(t)


@router.post("/tasks/{task_id}/release")
def release(task_id: int, s: SessionDep, email: Email, role: Role) -> dict[str, Any]:
    t = get_task(s, task_id, role)
    if t.status != "claimed" or t.assignee != email:
        raise HTTPException(status.HTTP_409_CONFLICT, "only the person who claimed a task can release it")
    t.status, t.assignee = "open", None
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
    request_event = Event.from_json(t.request_json)
    add_to_outbox(s, request_event.reply("TaskCompleted", {"outputs": outputs, "completed_by": email}))
    t.status, t.result, t.completed_at = "done", outputs, now()
    s.commit()
    request.app.state.relay.notify()
    return task_out(t)


def create_app(db: Database | None = None, bus: Bus | None = None) -> FastAPI:
    """Build the service; tests and the dev stack pass a database and a shared bus."""
    database = db or Database(make_engine())
    owns_bus = bus is None
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    relay = OutboxRelay(database.sessions, the_bus)
    consumer = Consumer(database)
    the_bus.subscribe(
        "worklist",
        ["TaskRequested.worklist", "CaseFailed", "CaseCancelled", "CaseCompensated"],
        consumer.on_event,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        relay.start()
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()
        relay.stop()

    app = FastAPI(title="AdaptiveCare worklist", version="0.3.0", lifespan=lifespan)
    app.state.db, app.state.relay, app.state.consumer = database, relay, consumer
    app.include_router(router)
    return app
