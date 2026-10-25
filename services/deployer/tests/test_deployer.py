"""DEP-01: as an admin, deploying a published version starts its own engine container and queue."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from care_events import Event, InMemoryBus, OutboxRow
from deployer.db import Database, make_engine
from deployer.main import create_app
from deployer.psm import EngineConfig, engine_config
from fastapi.testclient import TestClient
from sqlalchemy import select

ADMIN = {"x-user-email": "admin@x.org"}
VERSIONS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "pathway_id": "triage", "number": 3, "status": "published"},
    2: {"id": 2, "pathway_id": "triage", "number": 4, "status": "draft"},
}


class FakeRuntime:
    def __init__(self, healthy_after: int = 1) -> None:
        self.started: list[EngineConfig] = []
        self.stopped: list[str] = []
        self.healthy_after = healthy_after
        self.checks = 0

    def start(self, cfg: EngineConfig) -> None:
        self.started.append(cfg)

    def healthy(self, cfg: EngineConfig) -> bool:
        self.checks += 1
        return self.healthy_after > 0 and self.checks >= self.healthy_after

    def stop(self, cfg: EngineConfig) -> None:
        self.stopped.append(cfg.name)

    def url(self, cfg: EngineConfig) -> str | None:
        return f"http://{cfg.name}:8000"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(make_engine(f"sqlite:///{tmp_path / 'deployer.db'}"))
    yield database
    database.engine.dispose()


def client_with(db: Database, runtime: FakeRuntime, timeout: float = 5) -> TestClient:
    return TestClient(
        create_app(
            db, InMemoryBus(), runtime, fetch_version=lambda vid: VERSIONS[vid], health_timeout_s=timeout
        )
    )


def test_psm_names_queue_schema_and_environment() -> None:
    cfg = engine_config("lab_orders", 2, 17, "adaptivecare/engine:dev", {"AMQP_URL": "amqp://x"})
    assert (cfg.name, cfg.queue, cfg.schema) == (
        "engine-lab-orders-v2",
        "engine.lab_orders.v2",
        "engine_lab_orders_v2",
    )
    assert cfg.env == {
        "AMQP_URL": "amqp://x",
        "ENGINE_VERSION_ID": "17",
        "ENGINE_SCHEMA": "engine_lab_orders_v2",
    }
    assert cfg.labels["adaptivecare.role"] == "engine"
    with pytest.raises(ValueError):
        engine_config("Bad; DROP", 1, 1, "img", {})


def test_dep01_deploy_starts_the_engine_waits_for_health_and_announces_it(db: Database) -> None:
    runtime = FakeRuntime(healthy_after=3)
    with client_with(db, runtime) as client:
        r = client.post("/versions/1/deploy", headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert (d["status"], d["container"], d["queue"]) == (
            "running",
            "engine-triage-v3",
            "engine.triage.v3",
        )
        assert d["requested_by"] == "admin@x.org" and d["healthy_at"]
        assert [c.name for c in runtime.started] == ["engine-triage-v3"] and runtime.checks == 3
        with db.sessions() as s:
            event = Event.from_json(s.scalars(select(OutboxRow)).one().event_json)
        assert event.type == "PathwayDeployed" and (event.pathway, event.version) == ("triage", 3)
        assert [x["status"] for x in client.get("/deployments").json()] == ["running"]


def test_deploying_twice_reuses_the_running_engine(db: Database) -> None:
    runtime = FakeRuntime()
    with client_with(db, runtime) as client:
        first = client.post("/versions/1/deploy", headers=ADMIN).json()
        second = client.post("/versions/1/deploy", headers=ADMIN).json()
    assert first["id"] == second["id"] and len(runtime.started) == 1


def test_only_published_versions_can_be_deployed(db: Database) -> None:
    runtime = FakeRuntime()
    with client_with(db, runtime) as client:
        r = client.post("/versions/2/deploy", headers=ADMIN)
    assert r.status_code == 409 and "published" in r.json()["detail"] and runtime.started == []


def test_an_engine_that_never_becomes_healthy_is_stopped_and_marked_failed(db: Database) -> None:
    runtime = FakeRuntime(healthy_after=0)  # never healthy
    with client_with(db, runtime, timeout=0.5) as client:
        r = client.post("/versions/1/deploy", headers=ADMIN)
        assert r.status_code == 504 and "not healthy" in r.json()["detail"]
        assert runtime.stopped == ["engine-triage-v3"]
        [d] = client.get("/deployments").json()
    assert d["status"] == "failed" and "not healthy" in d["error"]
    with db.sessions() as s:
        assert s.scalars(select(OutboxRow)).all() == []  # nothing announced


def test_restart_brings_running_deployments_back(db: Database) -> None:
    with client_with(db, FakeRuntime()) as client:
        client.post("/versions/1/deploy", headers=ADMIN)
    after_restart = FakeRuntime(healthy_after=0)  # the engine is gone
    with client_with(db, after_restart):
        pass
    assert [c.name for c in after_restart.started] == ["engine-triage-v3"]


# ---- DEP-02: undeploy drains, then retires --------------------------------------------


class FakeEngine:
    """Answers /drain and /health like an engine with ``running`` cases left."""

    def __init__(self, running: int) -> None:
        self.running, self.drained = running, False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drain":
            self.drained = True
            return httpx.Response(200, json={"draining": True})
        return httpx.Response(
            200, json={"status": "ok", "running_cases": self.running, "draining": self.drained}
        )


def test_dep02_undeploy_drains_and_retires_when_the_last_case_ends(db: Database) -> None:
    engine, runtime = FakeEngine(running=2), FakeRuntime()
    http = httpx.Client(transport=httpx.MockTransport(engine.handler))
    app = create_app(db, InMemoryBus(), runtime, fetch_version=lambda vid: VERSIONS[vid], engine_http=http)
    with TestClient(app) as client:
        dep = client.post("/versions/1/deploy", headers=ADMIN).json()
        r = client.delete(f"/deployments/{dep['id']}")
        assert r.status_code == 200 and r.json()["status"] == "draining" and engine.drained
        assert runtime.stopped == []  # two cases still running: the engine stays up
        engine.running = 0
        assert app.state.deployer.check_draining() == 1
        assert runtime.stopped == ["engine-triage-v3"]
        assert client.get("/deployments").json()[0]["status"] == "retired"
        assert client.delete(f"/deployments/{dep['id']}").json()["status"] == "retired"  # idempotent
    with db.sessions() as s:
        kinds = [
            Event.from_json(r.event_json).type for r in s.scalars(select(OutboxRow).order_by(OutboxRow.id))
        ]
    assert kinds == ["PathwayDeployed", "PathwayDraining", "PathwayRetired"]


def test_an_idle_engine_retires_at_once(db: Database) -> None:
    engine, runtime = FakeEngine(running=0), FakeRuntime()
    http = httpx.Client(transport=httpx.MockTransport(engine.handler))
    with TestClient(
        create_app(db, InMemoryBus(), runtime, fetch_version=lambda vid: VERSIONS[vid], engine_http=http)
    ) as c:
        dep = c.post("/versions/1/deploy", headers=ADMIN).json()
        assert c.delete(f"/deployments/{dep['id']}").json()["status"] == "retired"
        assert c.delete("/deployments/999").status_code == 404
