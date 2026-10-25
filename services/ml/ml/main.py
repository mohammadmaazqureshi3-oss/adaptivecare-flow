"""ml service: urgency prediction (KTAS level 1-5) as a pathway task.

Feature IDs: C2-04. Sprint 0 skeleton; the real endpoints arrive in Sprint 6.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare ml", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ml"}
