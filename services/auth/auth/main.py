"""auth service: users, roles, login, tokens, login log.

Feature IDs: C1-01, C4-03. Sprint 0 skeleton; the real endpoints arrive in Sprint 1.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="AdaptiveCare auth", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auth"}
