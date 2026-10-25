"""Pathway model: parsing, fallback normalisation and round trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pathway_core import ModelError, Pathway

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"


def load(name: str) -> dict:
    return json.loads((PATHWAYS / f"{name}.json").read_text())


def test_triage_loads() -> None:
    p = Pathway.from_dict(load("triage"))
    assert p.id == "triage" and p.node("vitals").role == "nurse"
    assert p.start_inputs == {"patient_id"}
    assert p.node("vitals").settings["deadline"]["minutes"] == 10


def test_fallback_becomes_an_edge() -> None:
    p = Pathway.from_dict(load("triage"))
    [fb] = [e for e in p.outgoing("predict") if e.fallback]
    assert fb.target == "manual_triage"


def test_round_trip_keeps_the_model() -> None:
    p = Pathway.from_dict(load("triage"))
    assert Pathway.from_dict(p.to_dict()) == p


@pytest.mark.parametrize(
    "doc",
    [
        {"id": "x", "nodes": [{"id": "a", "type": "blob"}], "edges": []},
        {"id": "x", "nodes": [{"id": "a", "type": "task"}], "edges": []},
        {"id": "x", "nodes": [{"id": "a", "type": "end"}, {"id": "a", "type": "end"}], "edges": []},
        {"id": "x", "variables": [{"name": "v", "type": "date"}], "nodes": [], "edges": []},
        {"id": "x", "nodes": []},
    ],
)
def test_bad_documents_are_rejected(doc: dict) -> None:
    with pytest.raises(ModelError):
        Pathway.from_dict(doc)
