"""CLN-01..03: Triage → Assessment → Visit, end to end, in process.

Real patient, ml (with the shipped urgency model), worklist and one engine per clinical
pathway share an in-memory bus that delivers every message twice. Pathways chain through
the events their End nodes announce (TriageCompleted, AdmissionRequested, PatientAdmitted).
Covers ML-02 inside a pathway, WRK-02 (override with a reason), PAT-02 (beds, undo),
CLN-04 (the NEWS2 score from the new scores service) and MON-01 (the case history).
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
from scores.main import create_app as scores_app
from worklist.db import Database as WorklistDB
from worklist.db import make_engine as worklist_db
from worklist.main import create_app as worklist_app

ROOT = Path(__file__).resolve().parents[2]
NURSE = {"x-user-email": "nadia@x.org", "x-user-role": "nurse"}
DOCTOR = {"x-user-email": "dev@x.org", "x-user-role": "doctor"}
SEVERE = {
    "spo2": 86,
    "sbp": 95,
    "hr": 120,
    "rr": 28,
    "temp": 37.2,
    "pain": 8,
    "mental": "alert",
    "oxygen": False,
}


class Hospital:
    def __init__(self, tmp: Path, stack: ExitStack) -> None:
        self.bus = InMemoryBus(deliver_twice=True)
        self.engines: dict[str, TestClient] = {}
        for name in ("triage", "assessment", "visit"):
            model = Pathway.from_dict(
                json.loads((ROOT / "pathways" / "clinical" / f"{name}.json").read_text())
            )
            store = Store(engine_db(f"sqlite:///{tmp / f'{name}.db'}"))
            stack.callback(store.engine.dispose)
            self.engines[name] = stack.enter_context(TestClient(engine_app(model, store, self.bus)))
        wl, pt = (
            WorklistDB(worklist_db(f"sqlite:///{tmp / 'wl.db'}")),
            PatientDB(patient_db(f"sqlite:///{tmp / 'pt.db'}")),
        )
        stack.callback(wl.engine.dispose)
        stack.callback(pt.engine.dispose)
        self.worklist = stack.enter_context(TestClient(worklist_app(wl, self.bus)))
        self.patient = stack.enter_context(TestClient(patient_app(pt, self.bus)))
        stack.enter_context(TestClient(ml_app(self.bus)))
        # CLN-04: the NEWS2 task type exists only because this service answers it.
        stack.enter_context(TestClient(scores_app(self.bus)))
        self.bus.start()
        stack.callback(self.bus.stop)

    def wait_for(self, check: Any, timeout: float = 15) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if result := check():
                return result
            time.sleep(0.05)
        raise TimeoutError("not reached")

    def do(
        self, label: str, headers: dict[str, str], outputs: dict[str, Any], reason: str | None = None
    ) -> dict[str, Any]:
        task = self.wait_for(
            lambda: next(
                (t for t in self.worklist.get("/tasks", headers=headers).json() if t["label"] == label), None
            )
        )
        self.worklist.post(f"/tasks/{task['id']}/claim", headers=headers)
        r = self.worklist.post(
            f"/tasks/{task['id']}/complete", json={"outputs": outputs, "reason": reason}, headers=headers
        )
        assert r.status_code == 200, r.text
        return dict(task)

    def case(self, pathway: str, status: str) -> dict[str, Any] | None:
        cases = self.engines[pathway].get("/cases").json()
        return next((c for c in cases if c["status"] == status), None)


@pytest.fixture
def hospital(tmp_path: Path) -> Iterator[Hospital]:
    with ExitStack() as es:
        yield Hospital(tmp_path, es)


def register(h: Hospital) -> str:
    h.patient.post("/beds", json={"id": "W1-01", "ward": "W1"})
    body = {
        "name": "Grace Hopper",
        "date_of_birth": "1950-12-09",
        "sex": "female",
        "arrival_mode": "ambulance",
        "chief_complaint": "chest pain, sweating",
    }
    return str(h.patient.post("/patients", json=body, headers=NURSE).json()["mrn"])


def through_triage(h: Hospital, mrn: str) -> dict[str, Any]:
    h.do("Measure vital signs", NURSE, SEVERE)
    # CLN-01 + ML-02: the model predicts; low oxygen routes to the urgent confirmation (safety rule).
    confirm = h.wait_for(
        lambda: next(
            (
                t
                for t in h.worklist.get("/tasks", headers=NURSE).json()
                if t["label"] == "Confirm urgency (urgent)"
            ),
            None,
        )
    )
    assert confirm["patient_id"] == mrn and confirm["inputs"]["triage_note"].startswith("ML urgency-v1")
    assert confirm["inputs"]["news2"] >= 7 and confirm["inputs"]["news2_risk"] == "high"  # CLN-04
    suggested = confirm["inputs"]["urgency"]
    decided = 1 if suggested != 1 else 2
    # WRK-02: changing the model's level without a reason is refused, with one it is logged.
    h.worklist.post(f"/tasks/{confirm['id']}/claim", headers=NURSE)
    refused = h.worklist.post(
        f"/tasks/{confirm['id']}/complete", json={"outputs": {"confirmed_urgency": decided}}, headers=NURSE
    )
    assert refused.status_code == 422
    ok = h.worklist.post(
        f"/tasks/{confirm['id']}/complete",
        json={"outputs": {"confirmed_urgency": decided}, "reason": "Grey, clammy, worsening chest pain"},
        headers=NURSE,
    )
    assert ok.status_code == 200
    return dict(confirm)


def through_assessment(h: Hospital, admit: bool) -> None:
    h.do("Blood tests", NURSE, {"lab_abnormal": True})
    h.do("Imaging and report", DOCTOR, {"imaging_abnormal": False})
    h.do("Doctor review", DOCTOR, {"admit": admit, "plan": "cardiology ward, serial troponin"})


def test_cln01_to_03_a_patient_goes_from_registration_to_a_ward_bed(hospital: Hospital) -> None:
    h = hospital
    mrn = register(h)
    through_triage(h, mrn)
    assert h.wait_for(lambda: h.case("triage", "completed"))
    [log] = h.worklist.get("/overrides").json()
    assert log["reason"].startswith("Grey") and log["patient_id"] == mrn
    # MON-01: the monitor recorded the case, including the override and the NEWS2 reply.
    [summary] = h.worklist.get("/cases", params={"pathway": "triage"}).json()
    history = h.worklist.get(f"/cases/{summary['case_id']}").json()["history"]
    assert any(e["detail"].get("override") for e in history)
    assert history[-1]["type"] == "TriageCompleted" or history[-2]["type"] == "CaseCompleted"

    # CLN-02: TriageCompleted starts the Assessment case; labs and imaging run in parallel.
    through_assessment(h, admit=True)
    assessment = h.wait_for(lambda: h.case("assessment", "completed"))
    detail = h.engines["assessment"].get(f"/cases/{assessment['id']}").json()
    assert detail["joins_fired"] == {"results": 1} and detail["data"]["confirmed_urgency"] in (1, 2)

    # CLN-03: AdmissionRequested starts the Visit; the patient service reserves the bed (PAT-02).
    h.do("Prepare ward handover", NURSE, {})
    transfer = h.do("Transfer to ward", NURSE, {})
    assert transfer["inputs"]["bed_id"] == "W1-01"
    assert h.wait_for(lambda: h.case("visit", "completed"))
    bed = h.wait_for(
        lambda: next((b for b in h.patient.get("/beds").json() if b["status"] == "occupied"), None)
    )
    assert bed["id"] == "W1-01" and bed["patient_id"] == mrn


def test_cln03_a_failed_transfer_releases_the_bed_and_compensates_the_visit(hospital: Hospital) -> None:
    h = hospital
    through_triage(h, register(h))
    through_assessment(h, admit=True)
    h.do("Prepare ward handover", NURSE, {})
    transfer = h.wait_for(
        lambda: next(
            (t for t in h.worklist.get("/tasks", headers=NURSE).json() if t["label"] == "Transfer to ward"),
            None,
        )
    )
    assert h.patient.get("/beds").json()[0]["status"] == "reserved"
    h.worklist.post(f"/tasks/{transfer['id']}/claim", headers=NURSE)
    r = h.worklist.post(
        f"/tasks/{transfer['id']}/fail", json={"reason": "ward closed for infection control"}, headers=NURSE
    )
    assert r.status_code == 200
    assert h.wait_for(lambda: h.case("visit", "compensated"))
    assert h.wait_for(lambda: h.patient.get("/beds").json()[0]["status"] == "free")


def test_cln02_discharge_ends_without_a_visit(hospital: Hospital) -> None:
    h = hospital
    through_triage(h, register(h))
    through_assessment(h, admit=False)
    h.do("Discharge with advice", NURSE, {})
    assert h.wait_for(lambda: h.case("assessment", "completed"))
    time.sleep(0.3)
    assert h.engines["visit"].get("/cases").json() == []


def test_cln04_when_the_score_keeps_failing_a_nurse_calculates_news2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: dict[str, Any]) -> None:
        raise RuntimeError("scoring library crashed")

    monkeypatch.setattr("scores.main.news2", broken)  # every attempt fails temporarily
    with ExitStack() as es:
        h = Hospital(tmp_path, es)
        register(h)
        h.do("Measure vital signs", NURSE, SEVERE)
        # The engine retried twice with backoff, then took the fallback the designer drew.
        h.do("Calculate NEWS2 by hand", NURSE, {"news2": 12, "news2_risk": "high"})
        confirm = h.wait_for(
            lambda: next(
                (
                    t
                    for t in h.worklist.get("/tasks", headers=NURSE).json()
                    if t["label"].startswith("Confirm")
                ),
                None,
            )
        )
        assert confirm["inputs"]["news2"] == 12
