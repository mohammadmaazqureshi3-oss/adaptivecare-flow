"""MON-01 (case history for admins, doctors, managers) and MON-02 (the manager's dashboard)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from care_events import Event, InMemoryBus
from fastapi.testclient import TestClient
from worklist.db import Database, TaskRow, make_engine
from worklist.main import create_app
from worklist.monitor import dashboard

NURSE = {"x-user-email": "nadia@x.org", "x-user-role": "nurse"}
T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


def ev(type_: str, case: str, minute: float, pathway: str = "triage", **payload: Any) -> Event:
    return Event(
        type_,
        payload,
        event_id=f"{case}-{type_}-{minute}",
        case_id=case,
        token_id=payload.pop("token", None),
        pathway=pathway,
        version=2,
        timestamp=(T0 + timedelta(minutes=minute)).isoformat(),
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    db = Database(make_engine(f"sqlite:///{tmp_path / 'wl.db'}"))
    with TestClient(create_app(db, InMemoryBus())) as c:
        yield c
    db.engine.dispose()


def feed(client: TestClient, *events: Event) -> None:
    for e in events:
        client.app.state.monitor.on_event(e)  # type: ignore[attr-defined]


def journey(client: TestClient) -> None:
    feed(
        client,
        ev("CaseStarted", "c1", 0, patient_id="P000007", trigger="PatientRegistered"),
        ev(
            "TaskRequested",
            "c1",
            0.1,
            node="vitals",
            label="Measure vital signs",
            role="nurse",
            inputs={"name": "never kept"},
            token="w1",
        ),  # fmt: skip
        ev("TaskCompleted", "c1", 4, outputs={"spo2": 86}, completed_by="nadia@x.org", token="w1"),
        ev(
            "TaskCompleted",
            "c1",
            5,
            outputs={"confirmed_urgency": 1},
            completed_by="nadia@x.org",
            override={"suggested": 2, "decided": 1, "reason": "grey and clammy"},
        ),  # fmt: skip
        ev("CaseCompleted", "c1", 6, end="end", data={"urgency": 1}),
        ev("CaseStarted", "c2", 6.1, pathway="assessment", patient_id="P000007", trigger="TriageCompleted"),
        ev("CaseStarted", "c3", 7, patient_id="P000008", trigger="PatientRegistered"),
        ev("CaseFailed", "c3", 9, reason="start inputs missing"),
    )


def test_mon01_the_history_of_a_case_and_the_patients_journey(client: TestClient) -> None:
    journey(client)
    feed(client, ev("TaskCompleted", "c1", 4, outputs={"spo2": 86}, token="w1"))  # duplicate delivery
    feed(client, Event("PatientRegistered", {"patient_id": "P000009"}))  # no case: ignored
    case = client.get("/cases/c1").json()
    assert case["status"] == "completed" and case["patient_id"] == "P000007" and case["events"] == 5
    assert [h["type"] for h in case["history"]] == [
        "CaseStarted", "TaskRequested", "TaskCompleted", "TaskCompleted", "CaseCompleted",
    ]  # fmt: skip
    assert case["history"][1]["detail"] == {"node": "vitals", "label": "Measure vital signs", "role": "nurse"}
    assert case["history"][3]["detail"]["override"]["reason"] == "grey and clammy"
    assert [(j["pathway"], j["status"]) for j in case["journey"]] == [
        ("triage", "completed"),
        ("assessment", "running"),
    ]
    assert client.get("/cases/nope").status_code == 404


def test_mon01_cases_list_with_filters(client: TestClient) -> None:
    journey(client)
    assert [c["case_id"] for c in client.get("/cases").json()] == ["c3", "c2", "c1"]
    assert [c["case_id"] for c in client.get("/cases", params={"status": "failed"}).json()] == ["c3"]
    assert client.get("/cases", params={"status": "failed"}).json()[0]["reason"] == "start inputs missing"
    assert [c["case_id"] for c in client.get("/cases", params={"pathway": "assessment"}).json()] == ["c2"]
    assert [c["case_id"] for c in client.get("/cases", params={"patient": "p000007"}).json()] == ["c2", "c1"]


def task(**fields: Any) -> TaskRow:
    base: dict[str, Any] = dict(
        request_event_id=fields.pop("rid"), request_json="{}", case_id="c", pathway="triage", version=2,
        node="n", label="L", role="nurse", inputs={}, outputs=[], created_at=T0,
    )  # fmt: skip
    return TaskRow(**(base | fields))


def test_mon02_dashboard_counts_cases_queues_waits_and_missed_deadlines(client: TestClient) -> None:
    journey(client)
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    at = T0 + timedelta(minutes=60)
    with db.sessions.begin() as s:
        s.add_all(
            [
                # claimed after 4 min, done on time
                task(rid="a", status="done", claimed_at=T0 + timedelta(minutes=4),
                     completed_at=T0 + timedelta(minutes=8), due_at=T0 + timedelta(minutes=10)),
                # claimed after 20 min, finished late, escalated once
                task(rid="b", status="done", claimed_at=T0 + timedelta(minutes=20), level=1,
                     completed_at=T0 + timedelta(minutes=30), due_at=T0 + timedelta(minutes=10)),
                # still open and overdue now
                task(rid="c", status="open", due_at=T0 + timedelta(minutes=30), role="doctor",
                     created_at=T0 + timedelta(minutes=15)),
                task(rid="d", status="cancelled", due_at=T0),  # cancelled: not counted as missed
            ]
        )  # fmt: skip
    with db.sessions() as s:
        d = dashboard(s, at=at)
    assert d["active_cases"] == {"assessment": 1}
    assert d["ended_cases"] == {"completed": 1, "failed": 1}
    assert d["queues"] == {"doctor": {"open": 1, "oldest_min": 45.0, "overdue": 1}}
    assert d["waits"] == {"nurse": {"claimed": 2, "mean_min": 12.0, "p90_min": 20.0}}
    assert d["deadlines"] == {"with_deadline": 3, "missed": 2, "missed_rate": 0.667, "escalated": 1}
    assert client.get("/dashboard").status_code == 200


def test_mon02_claiming_records_the_wait_and_releasing_resets_it(client: TestClient) -> None:
    client.app.state.consumer.on_event(  # type: ignore[attr-defined]
        Event(
            "TaskRequested",
            {"label": "L", "role": "nurse", "outputs": []},
            event_id="r1",
            case_id="c",
            token_id="w",
            pathway="triage",
            version=1,
            target="worklist",
        )  # fmt: skip
    )
    [t] = client.get("/tasks", headers=NURSE).json()
    assert client.post(f"/tasks/{t['id']}/claim", headers=NURSE).json()["claimed_at"] is not None
    assert client.post(f"/tasks/{t['id']}/release", headers=NURSE).json()["claimed_at"] is None
