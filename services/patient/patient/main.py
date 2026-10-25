"""patient service: patients, triage records, beds (reserve and release).

Feature IDs: C1-02. Sprint 0 skeleton; the real endpoints arrive in Sprint 2.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare patient", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "patient"}
