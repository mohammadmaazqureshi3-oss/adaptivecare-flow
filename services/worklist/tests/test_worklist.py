"""WRK-01: as a nurse or doctor, I see tasks for my role, claim them and complete them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from care_events import Event, InMemoryBus, OutboxRow
from fastapi.testclient import TestClient
from sqlalchemy import select
from worklist.db import Database, TaskRow, make_engine
from worklist.main import create_app

NURSE = {"x-user-email": "nadia@x.org", "x-user-role": "nurse"}
NURSE2 = {"x-user-email": "nick@x.org", "x-user-role": "nurse"}
DOCTOR = {"x-user-email": "dev@x.org", "x-user-role": "doctor"}


def request(node: str = "vitals", role: str = "nurse", event_id: str = "req-1") -> Event:
    return Event(
        "TaskRequested",
        {
            "task_id": f"t0.1@{node}#1",
            "node": node,
            "label": "Measure vital signs",
            "role": role,
            "inputs": {"patient_id": "P000001"},
            "outputs": [{"name": "spo2", "type": "int"}, {"name": "note", "type": "string"}],
            "deadline": {"minutes": 10, "escalation": []},
            "patient_id": "P000001",
        },
        event_id=event_id,
        case_id="case-1",
        token_id=f"t0.1@{node}#1",
        pathway="triage",
        version=1,
        target="worklist",
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(make_engine(f"sqlite:///{tmp_path / 'worklist.db'}"))
    yield database
    database.engine.dispose()


@pytest.fixture
def client(db: Database) -> Iterator[TestClient]:
    with TestClient(create_app(db, InMemoryBus())) as c:
        yield c


def deliver(client: TestClient, event: Event) -> None:
    client.app.state.consumer.on_event(event)  # type: ignore[attr-defined]


def test_wrk01_a_requested_task_appears_for_its_role_only(client: TestClient) -> None:
    deliver(client, request())
    deliver(client, request())  # duplicate delivery
    [task] = client.get("/tasks", headers=NURSE).json()
    assert task["label"] == "Measure vital signs" and task["status"] == "open" and task["deadline_min"] == 10
    assert task["inputs"] == {"patient_id": "P000001"}
    assert client.get("/tasks", headers=DOCTOR).json() == []
    assert client.post(f"/tasks/{task['id']}/claim", headers=DOCTOR).status_code == 404


def test_wrk01_claim_then_complete_sends_task_completed_back_to_the_engine(
    client: TestClient, db: Database
) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    assert (
        client.post(f"/tasks/{tid}/complete", json={"outputs": {}}, headers=NURSE).status_code == 409
    )  # not claimed
    assert client.post(f"/tasks/{tid}/claim", headers=NURSE).json()["assignee"] == "nadia@x.org"
    assert client.post(f"/tasks/{tid}/claim", headers=NURSE2).status_code == 409  # someone else has it
    assert client.get("/tasks", headers=NURSE2).json() == []  # claimed tasks leave the shared list
    done = client.post(
        f"/tasks/{tid}/complete", json={"outputs": {"spo2": 97, "note": "ok", "extra": 1}}, headers=NURSE
    )
    assert done.status_code == 200 and done.json()["result"] == {"spo2": 97, "note": "ok"}
    with db.sessions() as s:
        [row] = s.scalars(select(OutboxRow)).all()
    reply = Event.from_json(row.event_json)
    assert reply.type == "TaskCompleted" and reply.routing_key == "TaskCompleted.triage.v1"
    assert (reply.case_id, reply.token_id) == ("case-1", "t0.1@vitals#1")
    assert reply.payload == {"outputs": {"spo2": 97, "note": "ok"}, "completed_by": "nadia@x.org"}
    assert (
        client.post(
            f"/tasks/{tid}/complete", json={"outputs": {"spo2": 97, "note": "x"}}, headers=NURSE
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "outputs",
    [
        {},
        {"spo2": "97", "note": "ok"},
        {"spo2": 97.5, "note": "ok"},
        {"spo2": True, "note": "ok"},
        {"spo2": 97, "note": "  "},
    ],
)
def test_wrk01_required_outputs_are_checked(client: TestClient, outputs: dict) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    assert client.post(f"/tasks/{tid}/complete", json={"outputs": outputs}, headers=NURSE).status_code == 422


def test_release_puts_a_task_back(client: TestClient) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    assert client.post(f"/tasks/{tid}/release", headers=NURSE2).status_code == 409
    assert client.post(f"/tasks/{tid}/release", headers=NURSE).json()["status"] == "open"
    assert [t["id"] for t in client.get("/tasks", headers=NURSE2).json()] == [tid]


def test_a_failed_case_cancels_its_open_tasks(client: TestClient, db: Database) -> None:
    deliver(client, request())
    deliver(client, Event("CaseFailed", {"reason": "x"}, case_id="case-1"))
    assert client.get("/tasks", headers=NURSE).json() == []
    with db.sessions() as s:
        assert s.scalars(select(TaskRow.status)).all() == ["cancelled"]


def test_finished_tasks_can_be_listed(client: TestClient) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    client.post(f"/tasks/{tid}/complete", json={"outputs": {"spo2": 90, "note": "n"}}, headers=NURSE)
    assert client.get("/tasks", headers=NURSE).json() == []
    assert [
        t["status"] for t in client.get("/tasks", params={"include_done": True}, headers=NURSE).json()
    ] == ["done"]


# ---- Sprint 4: escalation, alerts, cancellation, undo tasks ----------------------------

CHARGE = {"x-user-email": "cara@x.org", "x-user-role": "charge_nurse"}
MANAGER = {"x-user-email": "mia@x.org", "x-user-role": "manager"}


def test_eng06_reassigned_task_moves_to_the_next_role_and_is_reopened(client: TestClient) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    reassign = Event(
        "TaskReassigned",
        {
            "task_id": "t0.1@vitals#1",
            "role": "charge_nurse",
            "level": 1,
            "due_at": "2026-10-25T10:15:00+00:00",
        },
        case_id="case-1",
    )
    deliver(client, reassign)
    deliver(client, reassign)  # duplicate
    assert client.get("/tasks", headers=NURSE).json() == []
    [task] = client.get("/tasks", headers=CHARGE).json()
    assert (task["status"], task["assignee"], task["level"]) == ("open", None, 1)
    assert task["due_at"].startswith("2026-10-25T10:15:00")


def test_an_older_escalation_does_not_undo_a_newer_one(client: TestClient) -> None:
    deliver(client, request())
    for level, role in ((2, "manager"), (1, "charge_nurse")):  # arrive out of order
        deliver(
            client,
            Event(
                "TaskReassigned", {"task_id": "t0.1@vitals#1", "role": role, "level": level}, case_id="case-1"
            ),
        )
    assert client.get("/tasks", headers=MANAGER).json()[0]["level"] == 2


def test_notifications_are_listed_for_their_role(client: TestClient) -> None:
    deliver(
        client, Event("NotificationRequested", {"role": "manager", "message": "still open"}, case_id="case-1")
    )
    deliver(
        client,
        Event("NotificationRequested", {"role": "charge_nurse", "message": "yours now"}, case_id="case-1"),
    )
    assert [n["message"] for n in client.get("/notifications", headers=MANAGER).json()] == ["still open"]
    admin = {"x-user-email": "a@x.org", "x-user-role": "admin"}
    assert len(client.get("/notifications", headers=admin).json()) == 2


def test_cancel_requested_cancels_the_task(client: TestClient) -> None:
    deliver(client, request())
    deliver(
        client, Event("CancelRequested", {"task_id": "t0.1@vitals#1"}, case_id="case-1", target="worklist")
    )
    assert client.get("/tasks", headers=NURSE).json() == []


def test_eng08_undo_task_answers_compensated(client: TestClient, db: Database) -> None:
    undo = Event(
        "CompensateRequested",
        {
            "task_id": "undo:bed#7",
            "node": "bed",
            "action": "ReleaseBed",
            "label": "Undo: Reserve bed",
            "role": "nurse",
            "patient_id": "P000001",
            "outputs": [],
            "inputs": {},
        },
        event_id="undo-1",
        case_id="case-1",
        token_id="undo:bed#7",
        pathway="visit",
        version=1,
        target="worklist",
    )
    deliver(client, undo)
    [task] = client.get("/tasks", headers=NURSE).json()
    assert task["kind"] == "undo" and task["label"] == "Undo: Reserve bed"
    client.post(f"/tasks/{task['id']}/claim", headers=NURSE)
    assert (
        client.post(f"/tasks/{task['id']}/complete", json={"outputs": {}}, headers=NURSE).status_code == 200
    )
    with db.sessions() as s:
        reply = Event.from_json(s.scalars(select(OutboxRow)).one().event_json)
    assert reply.type == "Compensated" and reply.routing_key == "Compensated.visit.v1"
    assert reply.token_id == "undo:bed#7" and reply.payload["ok"] is True


def test_compensation_does_not_cancel_its_own_undo_tasks(client: TestClient) -> None:
    deliver(
        client,
        Event(
            "CompensateRequested",
            {"task_id": "undo:x#1", "role": "nurse", "label": "Undo"},
            case_id="case-1",
            token_id="undo:x#1",
            target="worklist",
        ),
    )
    deliver(client, Event("CaseCompensated", {}, case_id="case-1"))
    assert [t["kind"] for t in client.get("/tasks", headers=NURSE).json()] == ["undo"]


# ---- WRK-02: override only with a reason; reporting a problem ---------------------------


def confirm_request() -> Event:
    return Event(
        "TaskRequested",
        {
            "node": "confirm",
            "label": "Confirm urgency",
            "role": "nurse",
            "patient_id": "P000009",
            "inputs": {"urgency": 2, "triage_note": "ML: level 2"},
            "outputs": [{"name": "confirmed_urgency", "type": "int"}],
            "override": {"suggested": "urgency", "decided": "confirmed_urgency"},
        },
        event_id="req-confirm",
        case_id="case-9",
        token_id="t0@confirm#4",
        pathway="triage",
        version=2,
        target="worklist",
    )


def claimed_confirm(client: TestClient) -> int:
    deliver(client, confirm_request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    return int(tid)


def test_wrk02_agreeing_with_the_suggestion_needs_no_reason(client: TestClient) -> None:
    tid = claimed_confirm(client)
    r = client.post(f"/tasks/{tid}/complete", json={"outputs": {"confirmed_urgency": 2}}, headers=NURSE)
    assert r.status_code == 200
    assert client.get("/overrides").json() == []


def test_wrk02_overriding_needs_a_reason_which_is_logged(client: TestClient, db: Database) -> None:
    tid = claimed_confirm(client)
    body = {"outputs": {"confirmed_urgency": 1}}
    r = client.post(f"/tasks/{tid}/complete", json=body, headers=NURSE)
    assert r.status_code == 422 and "needs a reason" in r.json()["detail"]
    r = client.post(f"/tasks/{tid}/complete", json={**body, "reason": "ok"}, headers=NURSE)
    assert r.status_code == 422  # too short to explain anything
    reason = "Patient grey and sweating; looks worse than the vitals suggest"
    assert (
        client.post(f"/tasks/{tid}/complete", json={**body, "reason": reason}, headers=NURSE).status_code
        == 200
    )
    [log] = client.get("/overrides").json()
    assert (log["suggested"], log["decided"], log["reason"], log["by"]) == ("2", "1", reason, "nadia@x.org")
    with db.sessions() as s:
        reply = Event.from_json(s.scalars(select(OutboxRow)).one().event_json)
    assert reply.payload["override"]["reason"] == reason and reply.payload["outputs"] == {
        "confirmed_urgency": 1
    }


def test_reporting_a_problem_fails_the_task(client: TestClient, db: Database) -> None:
    deliver(client, request())
    tid = client.get("/tasks", headers=NURSE).json()[0]["id"]
    assert (
        client.post(f"/tasks/{tid}/fail", json={"reason": "no porter available"}, headers=NURSE).status_code
        == 409
    )
    client.post(f"/tasks/{tid}/claim", headers=NURSE)
    assert client.post(f"/tasks/{tid}/fail", json={"reason": "no"}, headers=NURSE).status_code == 422
    r = client.post(f"/tasks/{tid}/fail", json={"reason": "no porter available"}, headers=NURSE)
    assert r.status_code == 200 and r.json()["status"] == "failed"
    with db.sessions() as s:
        reply = Event.from_json(s.scalars(select(OutboxRow)).one().event_json)
    assert reply.type == "TaskFailed" and reply.payload["temporary"] is False
