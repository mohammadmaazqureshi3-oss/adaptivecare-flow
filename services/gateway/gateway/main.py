"""gateway service: the single entry point for users (REST).

Feature IDs: C4-03. Sprint 0 skeleton: it reports the health of every service,
which is the Sprint 0 demo ("all services start with one command"). Token and
role checks on every route (NFR-SEC-01/02) arrive in Sprint 1, the proxy routes
of plan Section 9 as each service gains its endpoints.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare gateway", version="0.1.0")

SERVICES = ["auth", "designer", "verifier", "simulator", "deployer", "worklist", "patient", "ml"]


def service_url(name: str) -> str:
    return os.environ.get(f"{name.upper()}_URL", f"http://{name}:8000")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.get("/health/all")
async def health_all() -> dict[str, object]:
    """Ask every service for its health; used by the Sprint 0 demo and monitoring."""
    async with httpx.AsyncClient(timeout=2.0) as client:

        async def check(name: str) -> tuple[str, str]:
            try:
                r = await client.get(f"{service_url(name)}/health")
                return name, "ok" if r.status_code == 200 else f"http {r.status_code}"
            except httpx.HTTPError as exc:
                return name, f"down ({type(exc).__name__})"

        results = dict(await asyncio.gather(*(check(s) for s in SERVICES)))
    return {"status": "ok" if all(v == "ok" for v in results.values()) else "degraded", "services": results}
