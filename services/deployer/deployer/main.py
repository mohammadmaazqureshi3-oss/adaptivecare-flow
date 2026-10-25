"""deployer service: turns a published pathway version into its own running engine (DEP-01).

Feature IDs: C4-02. The only service allowed to use Docker (NFR-SEC-04); only admins
reach it (NFR-SEC-03, separation of duties: designers publish, admins deploy).

Deploy, as plan Section 9 describes:
1. fetch the version from the designer; it must be published;
2. generate the engine's container configuration from the model (PIM → PSM);
3. create its database schema, start the container, wait for its health check (≤ 30 s);
4. record the deployment and publish ``PathwayDeployed``.
Undeploy (DEP-02): the engine is told to drain (no new cases; running ones finish),
the version becomes Draining; a watcher stops the engine once no case is running, and the
version becomes Retired (``PathwayDraining``, ``PathwayRetired``).
"""

import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import httpx
from care_events import Bus, Event, OutboxRelay, add_to_outbox
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from deployer.db import Database, DeploymentRow, iso, make_engine, now
from deployer.psm import SAFE, EngineConfig, engine_config
from deployer.runtime import DockerRuntime, Runtime

log = logging.getLogger("deployer")
HEALTH_TIMEOUT_S = 30.0  # DEP-01 acceptance: healthy within 30 seconds
FetchVersion = Callable[[int], dict[str, Any]]
PLATFORM_ENV = ("DATABASE_URL", "AMQP_URL", "DESIGNER_URL")


def http_fetch_version(version_id: int) -> dict[str, Any]:
    url = os.environ.get("DESIGNER_URL", "http://designer:8000")
    r = httpx.get(f"{url}/versions/{version_id}", timeout=10)
    if r.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    r.raise_for_status()
    result: dict[str, Any] = r.json()
    return result


def deployment_out(d: DeploymentRow) -> dict[str, Any]:
    return {
        "id": d.id,
        "version_id": d.version_id,
        "pathway": d.pathway,
        "version": d.version,
        "container": d.container,
        "queue": d.queue,
        "schema": d.schema_name,
        "status": d.status,
        "error": d.error,
        "requested_by": d.requested_by,
        "started_at": iso(d.started_at),
        "healthy_at": iso(d.healthy_at),
    }


class Deployer:
    def __init__(
        self,
        db: Database,
        runtime: Runtime,
        fetch_version: FetchVersion,
        image: str,
        health_timeout_s: float = HEALTH_TIMEOUT_S,
        engine_http: httpx.Client | None = None,
    ) -> None:
        self.db, self.runtime, self.fetch_version = db, runtime, fetch_version
        self.image, self.health_timeout_s = image, health_timeout_s
        self.http = engine_http or httpx.Client(timeout=10)  # for talking to engines (drain, health)
        self.relay: OutboxRelay | None = None

    def deploy(self, version_id: int, requested_by: str) -> DeploymentRow:
        version = self.fetch_version(version_id)
        if version["status"] not in ("published", "deployed"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"only published versions can be deployed (this one is {version['status']})",
            )
        with self.db.sessions() as s:
            running = s.scalars(
                select(DeploymentRow).where(
                    DeploymentRow.version_id == version_id, DeploymentRow.status == "running"
                )
            ).first()
            if running is not None:
                return running  # deploying twice is harmless
        env = {k: os.environ[k] for k in PLATFORM_ENV if k in os.environ}
        cfg = engine_config(version["pathway_id"], version["number"], version_id, self.image, env)
        row = self._record(cfg, requested_by)
        try:
            self._create_schema(cfg.schema)
            self.runtime.start(cfg)
            self._wait_healthy(cfg)
        except Exception as exc:
            self.runtime.stop(cfg)
            self._finish(row.id, "failed", error=str(exc)[:500])
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, f"deploy failed: {exc}") from exc
        return self._finish(row.id, "running", cfg=cfg)

    def undeploy(self, deployment_id: int) -> DeploymentRow:
        """DEP-02: drain, then retire when the last running case has finished."""
        with self.db.sessions() as s:
            row = s.get(DeploymentRow, deployment_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "deployment not found")
        if row.status in ("draining", "retired"):
            return row
        if row.status != "running":
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"only running deployments can be undeployed ({row.status})"
            )
        cfg = EngineConfig(**json.loads(row.config_json))
        url = self.runtime.url(cfg)
        if url is None:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{cfg.name} is not reachable")
        self.http.post(f"{url}/drain").raise_for_status()
        updated = self._set_status(row.id, "draining", "PathwayDraining", cfg)
        self.check_draining()  # an engine with no running case retires at once
        return self._get(updated.id)

    def check_draining(self) -> int:
        """Retire every draining engine whose last case has finished; returns how many."""
        with self.db.sessions() as s:
            rows = s.scalars(select(DeploymentRow).where(DeploymentRow.status == "draining")).all()
        retired = 0
        for row in rows:
            cfg = EngineConfig(**json.loads(row.config_json))
            url = self.runtime.url(cfg)
            try:
                running = self.http.get(f"{url}/health").json()["running_cases"] if url else 0
            except (httpx.HTTPError, KeyError, ValueError):
                continue  # try again on the next check
            if running == 0:
                self.runtime.stop(cfg)
                self._set_status(row.id, "retired", "PathwayRetired", cfg)
                retired += 1
        return retired

    def _get(self, row_id: int) -> DeploymentRow:
        with self.db.sessions() as s:
            row = s.get(DeploymentRow, row_id)
        if row is None:
            raise RuntimeError(f"deployment {row_id} disappeared")
        return row

    def _set_status(self, row_id: int, state: str, event_type: str, cfg: EngineConfig) -> DeploymentRow:
        with self.db.sessions.begin() as s:
            row = s.get(DeploymentRow, row_id)
            if row is None:
                raise RuntimeError(f"deployment {row_id} disappeared")
            row.status = state
            payload = {"version_id": cfg.version_id, "container": cfg.name}
            add_to_outbox(s, Event(event_type, payload, pathway=cfg.pathway, version=cfg.version))
        if self.relay:
            self.relay.notify()
        return row

    def watch(self, stop: threading.Event, interval_s: float = 2.0) -> None:
        while not stop.wait(interval_s):
            try:
                self.check_draining()
            except Exception:
                log.exception("drain check failed; retrying")

    def resume(self) -> None:
        """After a deployer restart, make sure every running deployment is up again."""
        with self.db.sessions() as s:
            rows = s.scalars(select(DeploymentRow).where(DeploymentRow.status == "running")).all()
        for row in rows:
            cfg = EngineConfig(**json.loads(row.config_json))
            if not self.runtime.healthy(cfg):
                log.info("restarting %s", cfg.name)
                self.runtime.start(cfg)

    def _record(self, cfg: EngineConfig, requested_by: str) -> DeploymentRow:
        with self.db.sessions.begin() as s:
            row = DeploymentRow(
                version_id=cfg.version_id,
                pathway=cfg.pathway,
                version=cfg.version,
                container=cfg.name,
                queue=cfg.queue,
                schema_name=cfg.schema,
                config_json=json.dumps(asdict(cfg)),
                status="starting",
                requested_by=requested_by,
            )
            s.add(row)
        return row

    def _create_schema(self, schema: str) -> None:
        if not SAFE.match(schema):
            raise ValueError(f"unsafe schema name {schema!r}")
        if self.db.engine.dialect.name == "postgresql":
            with self.db.engine.begin() as conn:
                # The name was checked against SAFE above, so it is safe to put in the statement.
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    def _wait_healthy(self, cfg: EngineConfig) -> None:
        deadline = time.monotonic() + self.health_timeout_s
        while time.monotonic() < deadline:
            if self.runtime.healthy(cfg):
                return
            time.sleep(0.2)
        raise TimeoutError(f"{cfg.name} was not healthy within {self.health_timeout_s:g} s")

    def _finish(
        self, row_id: int, state: str, cfg: EngineConfig | None = None, error: str = ""
    ) -> DeploymentRow:
        with self.db.sessions.begin() as s:
            row = s.get(DeploymentRow, row_id)
            if row is None:
                raise RuntimeError(f"deployment {row_id} disappeared")
            row.status, row.error = state, error
            if state == "running" and cfg is not None:
                row.healthy_at = now()
                add_to_outbox(
                    s,
                    Event(
                        "PathwayDeployed",
                        {"version_id": cfg.version_id, "container": cfg.name, "queue": cfg.queue},
                        pathway=cfg.pathway,
                        version=cfg.version,
                    ),
                )
        if self.relay:
            self.relay.notify()
        return row


router = APIRouter()


def deployer_of(request: Request) -> Deployer:
    d: Deployer = request.app.state.deployer
    return d


def session(request: Request) -> Iterator[Session]:
    yield from deployer_of(request).db.session()


SessionDep = Annotated[Session, Depends(session)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deployer"}


@router.post("/versions/{version_id}/deploy")
def deploy(
    version_id: int, request: Request, author: Annotated[str, Header(alias="x-user-email")] = "unknown"
) -> dict[str, Any]:
    """DEP-01: start this published version as its own engine with its own queue."""
    return deployment_out(deployer_of(request).deploy(version_id, author))


@router.delete("/deployments/{deployment_id}")
def undeploy(deployment_id: int, request: Request) -> dict[str, Any]:
    """DEP-02: the version stops taking new cases and is retired when its last case ends."""
    return deployment_out(deployer_of(request).undeploy(deployment_id))


@router.get("/deployments")
def deployments(s: SessionDep, pathway: str | None = None) -> list[dict[str, Any]]:
    q = select(DeploymentRow).order_by(DeploymentRow.id.desc())
    if pathway:
        q = q.where(DeploymentRow.pathway == pathway)
    return [deployment_out(d) for d in s.scalars(q.limit(200))]


def create_app(
    db: Database | None = None,
    bus: Bus | None = None,
    runtime: Runtime | None = None,
    fetch_version: FetchVersion = http_fetch_version,
    health_timeout_s: float = HEALTH_TIMEOUT_S,
    engine_http: httpx.Client | None = None,
) -> FastAPI:
    """Build the service; tests pass a fake runtime and designer, the dev stack a local runtime."""
    database = db or Database(make_engine())
    the_runtime = runtime or DockerRuntime(network=os.environ.get("ENGINE_NETWORK", "adaptivecare_default"))
    image = os.environ.get("ENGINE_IMAGE", "adaptivecare/engine:dev")
    svc = Deployer(database, the_runtime, fetch_version, image, health_timeout_s, engine_http)
    owns_bus = bus is None
    the_bus: Bus | None = bus or (RabbitBus(os.environ["AMQP_URL"]) if os.environ.get("AMQP_URL") else None)
    svc.relay = OutboxRelay(database.sessions, the_bus) if the_bus else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if svc.relay:
            svc.relay.start()
        if owns_bus and the_bus:
            the_bus.start()
        svc.resume()
        stop = threading.Event()
        watcher = threading.Thread(target=svc.watch, args=(stop,), name="drain-watcher", daemon=True)
        watcher.start()
        yield
        stop.set()
        if owns_bus and the_bus:
            the_bus.stop()
        if svc.relay:
            svc.relay.stop()

    app = FastAPI(title="AdaptiveCare deployer", version="0.4.0", lifespan=lifespan)
    app.state.deployer = svc
    app.include_router(router)
    return app
