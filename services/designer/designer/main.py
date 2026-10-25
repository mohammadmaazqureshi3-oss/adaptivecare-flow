"""designer service: pathways and versions; runs Verify and Publish.

Feature IDs: C1-03. Stories: DES-01/02 (store what the editor draws), DES-03
(live condition checks), DES-05 (every Publish creates an immutable version),
and VER-01's rule that Publish needs a SAFE verification. The verifier itself is
Algorithm 1 in its own service; this one only calls it and stores the report.
Users reach it through the gateway, which has already checked their role and
passes their identity in ``X-User-Email``.
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from care_events import Bus, Event
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pathway_core import ModelError, Pathway
from pathway_core.conditions import ConditionSyntaxError, parse, typecheck
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from designer.db import Database, PathwayRow, VersionRow, iso, make_engine, now

VerifyFn = Callable[[dict[str, Any]], dict[str, Any]]
FROZEN = frozenset({"published", "deployed"})  # immutable from Publish on (DES-05)


class PathwayIn(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$", description="lowercase id, e.g. triage")
    name: str = Field(min_length=1, max_length=200)


class PathwayPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class VersionIn(BaseModel):
    model: dict[str, Any]


class Variable(BaseModel):
    name: str
    type: str


class ConditionIn(BaseModel):
    condition: str
    variables: list[Variable] = []


def http_verifier(model: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get("VERIFIER_URL", "http://verifier:8000")
    r = httpx.post(f"{url}/verify", json=model, timeout=30.0)
    if r.status_code == 422:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, r.json().get("detail", "invalid model"))
    r.raise_for_status()
    result: dict[str, Any] = r.json()
    return result


def starter_model(pathway_id: str, name: str) -> dict[str, Any]:
    """A new pathway starts as Start → End, so it is valid from its first save."""
    return {
        "id": pathway_id,
        "version": 1,
        "name": name,
        "variables": [],
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "x": 80, "y": 160},
            {"id": "end", "type": "end", "label": "End", "x": 480, "y": 160},
        ],
        "edges": [{"id": "start->end", "from": "start", "to": "end"}],
    }


def version_out(v: VersionRow, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": v.id,
        "pathway_id": v.pathway_id,
        "number": v.number,
        "status": v.status,
        "author": v.author,
        "updated_at": iso(v.updated_at),
        "published_at": iso(v.published_at) if v.published_at else None,
        "report_status": v.report["status"] if v.report else None,
    }
    if full:
        out |= {"model": v.model, "report": v.report}
    return out


def pathway_out(p: PathwayRow) -> dict[str, Any]:
    latest = p.versions[-1] if p.versions else None
    published = [v.number for v in p.versions if v.status in FROZEN]
    return {
        "id": p.id,
        "name": p.name,
        "created_by": p.created_by,
        "latest_version": version_out(latest, full=False) if latest else None,
        "published_versions": published,
    }


def validated(model: dict[str, Any], v: VersionRow) -> dict[str, Any]:
    """Check the model parses, and pin its id and version to the row it is saved in."""
    model = {**model, "id": v.pathway_id, "version": v.number}
    try:
        Pathway.from_dict(model)
    except ModelError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return model


def check_condition(body: ConditionIn) -> dict[str, Any]:
    try:
        tree = parse(body.condition)
    except ConditionSyntaxError as exc:
        return {"ok": False, "errors": [{"kind": "syntax", "message": exc.message, "pos": exc.pos}]}
    issues = typecheck(tree, {v.name: v.type for v in body.variables})
    errors = [{"kind": "type", "message": i.message, "pos": i.pos} for i in issues]
    return {"ok": not errors, "errors": errors}


router = APIRouter()


def session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    yield from db.session()


def verifier(request: Request) -> VerifyFn:
    fn: VerifyFn = request.app.state.verify
    return fn


SessionDep = Annotated[Session, Depends(session)]
Author = Annotated[str, Header(alias="x-user-email")]


def get_pathway(s: Session, pathway_id: str) -> PathwayRow:
    p = s.get(PathwayRow, pathway_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pathway not found")
    return p


def get_version(s: Session, version_id: int) -> VersionRow:
    v = s.get(VersionRow, version_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return v


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "designer"}


@router.get("/pathways")
def list_pathways(s: SessionDep) -> list[dict[str, Any]]:
    return [pathway_out(p) for p in s.scalars(select(PathwayRow).order_by(PathwayRow.id))]


@router.post("/pathways", status_code=status.HTTP_201_CREATED)
def create_pathway(body: PathwayIn, s: SessionDep, author: Author = "unknown") -> dict[str, Any]:
    if s.get(PathwayRow, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a pathway with this id exists")
    p = PathwayRow(id=body.id, name=body.name, created_by=author)
    p.versions.append(VersionRow(number=1, model=starter_model(body.id, body.name), author=author))
    s.add(p)
    s.commit()
    return pathway_out(p)


@router.get("/pathways/{pathway_id}")
def read_pathway(pathway_id: str, s: SessionDep) -> dict[str, Any]:
    return pathway_out(get_pathway(s, pathway_id))


@router.patch("/pathways/{pathway_id}")
def rename_pathway(pathway_id: str, body: PathwayPatch, s: SessionDep) -> dict[str, Any]:
    p = get_pathway(s, pathway_id)
    p.name = body.name
    s.commit()
    return pathway_out(p)


@router.get("/pathways/{pathway_id}/versions")
def list_versions(pathway_id: str, s: SessionDep) -> list[dict[str, Any]]:
    return [version_out(v, full=False) for v in get_pathway(s, pathway_id).versions]


@router.post("/pathways/{pathway_id}/versions", status_code=status.HTTP_201_CREATED)
def new_draft(pathway_id: str, s: SessionDep, author: Author = "unknown") -> dict[str, Any]:
    """Start the next version as a draft, copied from the latest one."""
    p = get_pathway(s, pathway_id)
    latest = p.versions[-1]
    if latest.status not in FROZEN:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"version {latest.number} is still a draft; edit that one"
        )
    number = latest.number + 1
    draft = VersionRow(number=number, model={**latest.model, "version": number}, author=author)
    p.versions.append(draft)
    s.commit()
    return version_out(draft)


@router.get("/versions/{version_id}")
def read_version(version_id: int, s: SessionDep) -> dict[str, Any]:
    return version_out(get_version(s, version_id))


@router.put("/versions/{version_id}")
def save_draft(version_id: int, body: VersionIn, s: SessionDep, author: Author = "unknown") -> dict[str, Any]:
    v = get_version(s, version_id)
    if v.status in FROZEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{v.status} versions are immutable; start a new draft")
    v.model = validated(body.model, v)
    v.status, v.report = "draft", None  # an edit invalidates the last verification
    v.author, v.updated_at = author, now()
    s.commit()
    return version_out(v)


@router.post("/versions/{version_id}/verify")
def verify_version(
    version_id: int, s: SessionDep, verify: Annotated[VerifyFn, Depends(verifier)]
) -> dict[str, Any]:
    v = get_version(s, version_id)
    report = verify(v.model)
    if v.status not in FROZEN:
        v.report = report
        v.status = "verified" if report["status"] == "SAFE" else "draft"
        s.commit()
    return version_out(v)


@router.post("/versions/{version_id}/publish")
def publish(version_id: int, s: SessionDep) -> dict[str, Any]:
    v = get_version(s, version_id)
    if v.status in FROZEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"this version is already {v.status}")
    if v.status != "verified":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Publish needs a SAFE verification of this exact version"
        )
    v.status, v.published_at = "published", now()
    s.commit()
    return version_out(v)


@router.post("/conditions/check")
def condition_check(body: ConditionIn) -> dict[str, Any]:
    return check_condition(body)


class DeploymentListener:
    """``PathwayDeployed`` from the deployer moves a published version to Deployed (U07)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def on_event(self, event: Event) -> None:
        with self.db.sessions.begin() as s:
            v = s.get(VersionRow, event.payload.get("version_id"))
            if v is not None and v.status == "published":
                v.status = "deployed"


def create_app(
    db: Database | None = None, verify: VerifyFn = http_verifier, bus: Bus | None = None
) -> FastAPI:
    """Build the service; tests pass an in-memory database, an in-process verifier and a bus."""
    database = db or Database(make_engine())
    owns_bus = bus is None
    the_bus: Bus | None = bus or (RabbitBus(os.environ["AMQP_URL"]) if os.environ.get("AMQP_URL") else None)
    if the_bus:
        the_bus.subscribe("designer", ["PathwayDeployed"], DeploymentListener(database).on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_bus and the_bus:
            the_bus.start()
        yield
        if owns_bus and the_bus:
            the_bus.stop()

    app = FastAPI(title="AdaptiveCare designer", version="0.4.0", lifespan=lifespan)
    app.state.db, app.state.verify = database, verify
    app.include_router(router)
    return app
