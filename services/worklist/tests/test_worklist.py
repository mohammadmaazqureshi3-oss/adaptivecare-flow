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
