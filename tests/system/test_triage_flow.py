"""System test (in process): a registered patient flows through the Triage pathway.

The real patient, engine, ml and worklist apps share one in-memory bus that delivers
every message twice. Only their REST APIs are used, as the web app would through the
gateway. ENG-01, ENG-02, ENG-03, ENG-05, WRK-01 together. The same flow over RabbitMQ
in Docker Compose is the Sprint 3 integration test still to run (Docker unavailable).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from care_events import InMemoryBus
from engine.main import create_app as engine_app
from engine.store import Store
from engine.store import make_engine as engine_db
from fastapi.testclient import TestClient
from ml.main import create_app as ml_app
from pathway_core import Pathway
from patient.db import Database as PatientDB
from patient.db import make_engine as patient_db
from patient.main import create_app as patient_app
from worklist.db import Database as WorklistDB
from worklist.db import make_engine as worklist_db
from worklist.main import create_app as worklist_app

ROOT = Path(__file__).resolve().parents[2]
NURSE = {"x-user-email": "nadia@x.org", "x-user-role": "nurse"}


class Stack:
    def __init__(self, tmp: Path, stack: ExitStack) -> None:
        self.bus = InMemoryBus(deliver_twice=True)
        triage = Pathway.from_dict(json.loads((ROOT / "pathways" / "triage.json").read_text()))
        engine_store = Store(engine_db(f"sqlite:///{tmp / 'engine.db'}"))
        worklist_store = WorklistDB(worklist_db(f"sqlite:///{tmp / 'worklist.db'}"))
        patient_store = PatientDB(patient_db(f"sqlite:///{tmp / 'patient.db'}"))
        for db in (engine_store, worklist_store, patient_store):
            stack.callback(db.engine.dispose)  # runs last, after the apps have stopped
        self.engine = stack.enter_context(TestClient(engine_app(triage, engine_store, self.bus)))
        self.worklist = stack.enter_context(TestClient(worklist_app(worklist_store, self.bus)))
        self.patient = stack.enter_context(TestClient(patient_app(patient_store, self.bus)))
        # No model file: ml fails permanently, as if the model were withdrawn (ML-02 fallback).
        stack.enter_context(TestClient(ml_app(self.bus, model_path=tmp / "no-model.joblib")))
        self.bus.start()
        stack.callback(self.bus.stop)

    def wait_for(self, check: Any, timeout: float = 10) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if result := check():
                return result
            time.sleep(0.05)
        raise TimeoutError("the stack did not get there")

    def tasks(self) -> list[dict[str, Any]]:
        return self.worklist.get("/tasks", headers=NURSE).json()

    def do(self, label: str, **outputs: Any) -> None:
        task = self.wait_for(lambda: next((t for t in self.tasks() if t["label"] == label), None))
        assert self.worklist.post(f"/tasks/{task['id']}/claim", headers=NURSE).status_code == 200
        r = self.worklist.post(f"/tasks/{task['id']}/complete", json={"outputs": outputs}, headers=NURSE)
        assert r.status_code == 200, r.text

    def cases(self) -> list[dict[str, Any]]:
        return self.engine.get("/cases").json()


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    with ExitStack() as es:
        yield Stack(tmp_path, es)


def register(stack: Stack, name: str) -> str:
    body = {"name": name, "date_of_birth": "1980-01-01", "sex": "female", "arrival_mode": "ambulance"}
    r = stack.patient.post("/patients", json=body, headers=NURSE)
    assert r.status_code == 201
    return str(r.json()["mrn"])


def test_a_registered_patient_flows_through_triage_to_completion(stack: Stack) -> None:
    mrn = register(stack, "Ada Lovelace")
    # ENG-01: the registration starts one case (despite every message arriving twice)
    case = stack.wait_for(lambda: stack.cases()[0] if stack.cases() else None)
    assert case["patient_id"] == mrn and len(stack.cases()) == 1
    # No model: ml fails permanently, the fallback asks a nurse instead.
    stack.wait_for(lambda: {t["label"] for t in stack.tasks()} == {"Manual triage", "Measure vital signs"})
    stack.do("Manual triage", urgency=4, confidence=0.9)
    stack.do("Measure vital signs", spo2=86)
    # ENG-03: low oxygen routes to confirmation whatever the urgency
    stack.do("Confirm urgent level", confirmed_urgency=2)
    done = stack.wait_for(lambda: (c := stack.cases()[0])["status"] == "completed" and c)
    detail = stack.engine.get(f"/cases/{done['id']}").json()
    assert detail["data"] == {
        "patient_id": mrn,
        "urgency": 4,
        "confidence": 0.9,
        "spo2": 86,
        "confirmed_urgency": 2,
    }
    assert detail["joins_fired"] == {"join1": 1}
    kinds = [h["type"] for h in detail["history"] if h["direction"] == "out"]
    assert kinds.count("TaskRequested") == 4 and kinds[-1] == "CaseCompleted"
    assert stack.tasks() == []


def test_two_patients_get_independent_cases(stack: Stack) -> None:
    register(stack, "Alan Turing")
    register(stack, "Grace Hopper")
    stack.wait_for(lambda: len(stack.tasks()) == 4)
    assert len(stack.cases()) == 2
    assert {t["patient_id"] for t in stack.tasks()} == {"P000001", "P000002"}


def test_eng06_an_overdue_task_reaches_the_charge_nurse_and_the_manager(stack: Stack) -> None:
    from datetime import UTC, datetime, timedelta

    register(stack, "Katherine Johnson")
    stack.wait_for(lambda: any(t["label"] == "Measure vital signs" for t in stack.tasks()))
    scheduler = stack.engine.app.state.scheduler  # type: ignore[attr-defined]
    charge = {"x-user-email": "cara@x.org", "x-user-role": "charge_nurse"}
    manager = {"x-user-email": "mia@x.org", "x-user-role": "manager"}

    scheduler.clock = lambda: datetime.now(UTC) + timedelta(minutes=11)  # past the 10-minute deadline
    scheduler.tick()
    task = stack.wait_for(lambda: next(iter(stack.worklist.get("/tasks", headers=charge).json()), None))
    assert task["label"] == "Measure vital signs" and task["level"] == 1
    assert "Measure vital signs" not in {t["label"] for t in stack.tasks()}

    scheduler.clock = lambda: datetime.now(UTC) + timedelta(minutes=17)  # charge nurse's 5 minutes are over
    scheduler.tick()
    alerts = stack.wait_for(lambda: stack.worklist.get("/notifications", headers=manager).json())
    assert "every escalation level" in alerts[0]["message"]
