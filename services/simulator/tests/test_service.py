"""The simulator service: background jobs, readiness errors, stored results (C1-06)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from models import triage, two_roles
from simulator.db import Database, make_engine
from simulator.main import create_app

VERSIONS = {1: triage(), 2: two_roles()}
SCENARIO = {"arrivals_per_hour": 6, "staff": {"nurse": 2}, "days": 3, "warmup_days": 1}


def fetch(version_id: int) -> dict[str, Any]:
    return {"id": version_id, "status": "published", "model": VERSIONS[version_id].to_dict()}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    db = Database(make_engine(f"sqlite:///{tmp_path / 'sim.db'}"))
    yield TestClient(create_app(db, fetch))
    db.engine.dispose()


def wait_done(client: TestClient, job_id: int, timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/simulations/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError


def test_sim01_a_job_runs_in_the_background_and_stores_its_result(client: TestClient) -> None:
    r = client.post(
        "/versions/1/simulations", json={"scenario": SCENARIO}, headers={"x-user-email": "d@x.org"}
    )
    assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
    job = wait_done(client, r.json()["id"])
    assert job["status"] == "done" and job["requested_by"] == "d@x.org"
    metrics = job["result"]["simulation"]["metrics"]
    assert {"mean", "low", "high", "half_width"} <= set(metrics["utilisation[nurse]"])
    assert job["result"]["roles"] == ["nurse"]
    assert [j["id"] for j in client.get("/simulations", params={"version_id": 1}).json()] == [job["id"]]


def test_sim03_advice_job(client: TestClient) -> None:
    body = {
        "scenario": {
            "arrivals_per_hour": 8,
            "staff": {"nurse": 1, "doctor": 1},
            "cost": {"nurse": 1, "doctor": 2.5},
            "days": 3,
            "targets": [{"task": "review", "max_wait_min": 15, "max_share": 0.1}],
        },
        "advise": True,
        "budget": 40,
    }
    job = wait_done(client, client.post("/versions/2/simulations", json=body).json()["id"])
    advice = job["result"]["advice"]
    assert job["status"] == "done" and advice["feasible"] and advice["staff"]["doctor"] >= 2
    assert job["result"]["targets"][0]["text"].startswith("at most 10% of patients")


def test_des06_unready_pathway_is_refused_with_the_list_of_issues(client: TestClient) -> None:
    r = client.post("/versions/1/simulations", json={"scenario": {**SCENARIO, "staff": {}}})
    assert r.status_code == 422 and "Role 'nurse' has no staff number" in r.json()["detail"]["issues"][0]


def test_bad_scenario_and_missing_budget(client: TestClient) -> None:
    assert (
        client.post("/versions/1/simulations", json={"scenario": {**SCENARIO, "days": 0}}).status_code == 422
    )
    assert (
        client.post("/versions/1/simulations", json={"scenario": SCENARIO, "advise": True}).status_code == 422
    )
    assert client.get("/simulations/999").status_code == 404
