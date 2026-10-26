"""engine service: Algorithm 2, one container per deployed pathway version.

Feature IDs: C3-02. It loads one published pathway version, listens on its own queue
(``engine.<pathway>.v<version>``) for the start trigger and for replies addressed to
it, and runs every case. Sprint 4's deployer starts it with ``ENGINE_VERSION_ID``; until
then it can also read a model file (``ENGINE_MODEL_FILE``).
"""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from care_events import Bus, OutboxRelay
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pathway_core import Pathway
from service_metrics import instrument
from sqlalchemy import select

from engine.service import EngineService, Scheduler
from engine.store import CaseRow, Store, make_engine


def load_pathway() -> Pathway:
    """The published version this engine runs, from the designer or a model file."""
    if path := os.environ.get("ENGINE_MODEL_FILE"):
        with open(path) as f:
            return Pathway.from_dict(json.load(f))
    version_id = os.environ["ENGINE_VERSION_ID"]
    url = os.environ.get("DESIGNER_URL", "http://designer:8000")
    v = httpx.get(f"{url}/versions/{version_id}", timeout=10).raise_for_status().json()
    if v["status"] not in ("published", "deployed"):
        raise RuntimeError(f"version {version_id} is {v['status']}; only published versions run")
    return Pathway.from_dict(v["model"])


router = APIRouter()


def engine_of(request: Request) -> EngineService:
    svc: EngineService = request.app.state.engine
    return svc


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    svc = engine_of(request)
    return {
        "status": "ok",
        "service": "engine",
        "pathway": svc.pathway.id,
        "version": svc.pathway.version,
        "draining": svc.draining,
        "running_cases": svc.running_cases(),
    }


@router.post("/drain")
def drain(request: Request) -> dict[str, Any]:
    """DEP-02 (called by the deployer): no new cases; running cases finish."""
    svc = engine_of(request)
    svc.drain()
    return {"draining": True, "running_cases": svc.running_cases()}


@router.get("/cases")
def list_cases(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    svc = engine_of(request)
    with svc.store.sessions() as s:
        q = select(CaseRow).order_by(CaseRow.started_at.desc())
        if status:
            q = q.where(CaseRow.status == status)
        return [
            {
                "id": c.id,
                "patient_id": c.patient_id,
                "status": c.status,
                "updated_at": c.updated_at.isoformat(),
            }
            for c in s.scalars(q.limit(200))
        ]


@router.get("/cases/{case_id}")
def read_case(case_id: str, request: Request) -> dict[str, Any]:
    svc = engine_of(request)
    case = svc.load(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return svc.case_view(case)


def create_app(pathway: Pathway | None = None, store: Store | None = None, bus: Bus | None = None) -> FastAPI:
    """Build an engine for one pathway version. Tests and the dev stack pass the pieces in."""
    pathway = pathway or load_pathway()
    store = store or Store(make_engine())
    owns_bus = bus is None  # a bus passed in (tests, dev stack) is started and stopped by its owner
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    relay = OutboxRelay(store.sessions, the_bus)
    svc = EngineService(pathway, store, relay)
    scheduler = Scheduler(svc)
    the_bus.subscribe(svc.queue_name, svc.bindings, svc.on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        relay.start()
        scheduler.start()
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()
        scheduler.stop()
        relay.stop()

    app = FastAPI(
        title=f"AdaptiveCare engine {pathway.id} v{pathway.version}", version="0.3.0", lifespan=lifespan
    )
    app.state.engine, app.state.scheduler = svc, scheduler
    app.state.metrics = metrics = instrument(app, "engine")
    metrics.gauge("engine_running_cases", "Cases still running in this engine.", svc.running_cases)
    app.include_router(router)
    return app
