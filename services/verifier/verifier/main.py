"""verifier service: Algorithm 1 behind REST. Stateless; the designer service calls it."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pathway_core import ModelError, Pathway
from service_metrics import instrument

from verifier.algorithm import DEFAULT_LIMIT, verify

app = FastAPI(title="AdaptiveCare verifier", version="0.1.0")
app.state.metrics = instrument(app, "verifier")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "verifier"}


@app.post("/verify")
def verify_pathway(doc: dict[str, Any], limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Verify one pathway version (its JSON model). Returns SAFE, UNSAFE or TOO_LARGE."""
    try:
        pathway = Pathway.from_dict(doc)
    except ModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return verify(pathway, limit=limit).to_dict()
