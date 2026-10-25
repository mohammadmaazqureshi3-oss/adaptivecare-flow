"""deployer service: generates each engine's container configuration, starts and stops it.

The only service allowed to use Docker (NFR-SEC-04).

Feature IDs: C4-02. Sprint 0 skeleton; the real endpoints arrive in Sprint 4.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare deployer", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deployer"}
