"""worklist service: tasks for people (claim, complete, override).

Also notifications and case summaries for dashboards.

Feature IDs: C1-04, C1-05, C1-07, C2-07. Sprint 0 skeleton; the real endpoints arrive in Sprint 3.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare worklist", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "worklist"}
