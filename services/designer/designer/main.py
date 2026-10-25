"""designer service: pathways and versions; runs Verify, Simulate and Publish; asks the deployer to deploy.

Feature IDs: C1-03. Sprint 0 skeleton; the real endpoints arrive in Sprint 1.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare designer", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "designer"}
