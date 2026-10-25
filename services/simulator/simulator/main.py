"""simulator service: algorithm 3: Pathway Simulator and Staffing Advisor; long jobs run in the background.

Feature IDs: C3-03, C1-06. Sprint 0 skeleton; the real endpoints arrive in Sprint 5.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare simulator", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "simulator"}
