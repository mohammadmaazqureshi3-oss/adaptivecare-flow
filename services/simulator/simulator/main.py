"""simulator service: Algorithm 3, the Pathway Simulator and Staffing Advisor.

Feature IDs: C3-03, C1-06. Long jobs run in the background: ``POST`` returns a job id,
the client polls ``GET /simulations/{job}`` (plan Section 9). Designers and managers
reach it through the gateway.
"""

import logging
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pathway_core import ModelError, Pathway
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from simulator.advisor import advise
from simulator.db import Database, JobRow, iso, make_engine, now
from simulator.scenario import Scenario, human_roles, readiness_issues
from simulator.stats import replicate

log = logging.getLogger("simulator")
FetchVersion = Callable[[int], dict[str, Any]]


class SimulationIn(BaseModel):
    scenario: dict[str, Any]
    advise: bool = False  # SIM-03: also search for the cheapest staffing
    budget: float | None = None


def http_fetch_version(version_id: int) -> dict[str, Any]:
    url = os.environ.get("DESIGNER_URL", "http://designer:8000")
    r = httpx.get(f"{url}/versions/{version_id}", timeout=10)
    if r.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    r.raise_for_status()
    result: dict[str, Any] = r.json()
    return result


def job_out(j: JobRow) -> dict[str, Any]:
    return {
        "id": j.id,
        "version_id": j.version_id,
        "pathway": j.pathway,
        "version": j.version,
        "kind": j.kind,
        "scenario": j.scenario,
        "budget": j.budget,
        "status": j.status,
        "result": j.result,
        "error": j.error,
        "requested_by": j.requested_by,
        "created_at": iso(j.created_at),
        "finished_at": iso(j.finished_at),
    }


class Jobs:
    def __init__(self, db: Database, fetch_version: FetchVersion, workers: int = 2) -> None:
        self.db, self.fetch_version = db, fetch_version
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="simulation")

    def submit(self, version_id: int, body: SimulationIn, author: str) -> JobRow:
        v = self.fetch_version(version_id)
        try:
            p, sc = Pathway.from_dict(v["model"]), Scenario.from_dict(body.scenario)
        except (ModelError, ValueError, TypeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        issues = readiness_issues(p, sc)
        if issues:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "not ready to simulate", "issues": issues}
            )
        if body.advise and body.budget is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "staffing advice needs a budget")
        with self.db.sessions.begin() as s:
            job = JobRow(
                version_id=version_id,
                pathway=p.id,
                version=p.version,
                kind="advise" if body.advise else "simulate",
                scenario=sc.to_dict(),
                budget=body.budget,
                requested_by=author,
            )
            s.add(job)
        self.pool.submit(self._run, job.id, p, sc)
        return job

    def _run(self, job_id: int, p: Pathway, sc: Scenario) -> None:
        self._set(job_id, status="running")
        try:
            with self.db.sessions() as s:
                job = s.get(JobRow, job_id)
                kind, budget = (job.kind, job.budget) if job else ("simulate", None)
            if kind == "advise":
                advice = advise(p, sc, budget or 0.0)
                result: dict[str, Any] = {"advice": advice.to_dict()}
            else:
                result = {"simulation": replicate(p, sc).to_dict()}
            result["roles"] = human_roles(p)
            result["targets"] = [
                {"metric": t.metric, "limit": t.max_share, "text": t.describe()} for t in sc.targets
            ]
            self._set(job_id, status="done", result=result, finished_at=now())
        except Exception as exc:
            log.exception("simulation %s failed", job_id)
            self._set(job_id, status="failed", error=str(exc)[:500], finished_at=now())

    def _set(self, job_id: int, **fields: Any) -> None:
        with self.db.sessions.begin() as s:
            job = s.get(JobRow, job_id)
            if job is not None:
                for k, v in fields.items():
                    setattr(job, k, v)


router = APIRouter()


def jobs_of(request: Request) -> Jobs:
    j: Jobs = request.app.state.jobs
    return j


def session(request: Request) -> Iterator[Session]:
    yield from jobs_of(request).db.session()


SessionDep = Annotated[Session, Depends(session)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "simulator"}


@router.post("/versions/{version_id}/simulations", status_code=status.HTTP_202_ACCEPTED)
def start(
    version_id: int,
    body: SimulationIn,
    request: Request,
    author: Annotated[str, Header(alias="x-user-email")] = "unknown",
) -> dict[str, Any]:
    """SIM-01/03: simulate a scenario (and optionally get staffing advice). Returns a job to poll."""
    return job_out(jobs_of(request).submit(version_id, body, author))


@router.get("/simulations/{job_id}")
def read(job_id: int, s: SessionDep) -> dict[str, Any]:
    job = s.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "simulation not found")
    return job_out(job)


@router.get("/simulations")
def list_jobs(s: SessionDep, version_id: int | None = None) -> list[dict[str, Any]]:
    q = select(JobRow).order_by(JobRow.id.desc())
    if version_id is not None:
        q = q.where(JobRow.version_id == version_id)
    return [job_out(j) for j in s.scalars(q.limit(50))]


def create_app(db: Database | None = None, fetch_version: FetchVersion = http_fetch_version) -> FastAPI:
    """Build the service; tests pass an in-memory database and a fake designer."""
    app = FastAPI(title="AdaptiveCare simulator", version="0.5.0")
    app.state.jobs = Jobs(db or Database(make_engine()), fetch_version)
    app.include_router(router)
    return app
