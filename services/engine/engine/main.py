"""engine service: algorithm 2: Execution Engine (one container per deployed pathway version).

Feature IDs: C3-02. Sprint 0 skeleton; the real endpoints arrive in Sprint 3.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare engine", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "engine"}
