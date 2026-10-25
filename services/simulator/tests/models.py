"""Small pathways for simulator tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathway_core import Pathway

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"


def triage() -> Pathway:
    return Pathway.from_dict(json.loads((PATHWAYS / "triage.json").read_text()))


def single_queue(mean_min: float, role: str = "nurse", dist: str = "exponential") -> Pathway:
    """Start → one human task → End: an M/M/c queue when arrivals and durations are exponential."""
    return Pathway.from_dict(
        {
            "id": "mmc",
            "version": 1,
            "nodes": [
                {"id": "start", "type": "start", "trigger": "PatientRegistered"},
                {
                    "id": "see",
                    "type": "task",
                    "kind": "human",
                    "role": role,
                    "duration": {"dist": dist, "meanMin": mean_min},
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "start", "to": "see"}, {"from": "see", "to": "end"}],
        }
    )


def two_roles() -> Pathway:
    """A nurse step, then a doctor step: for the Staffing Advisor."""
    task = lambda i, role, mean: {  # noqa: E731
        "id": i,
        "type": "task",
        "kind": "human",
        "role": role,
        "duration": {"dist": "exponential", "meanMin": mean},
        "deadline": {"minutes": 30, "escalation": []},
    }
    doc: dict[str, Any] = {
        "id": "two",
        "version": 1,
        "nodes": [
            {"id": "start", "type": "start", "trigger": "PatientRegistered"},
            task("assess", "nurse", 9),
            task("review", "doctor", 14),
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "assess"},
            {"from": "assess", "to": "review"},
            {"from": "review", "to": "end"},
        ],
    }
    return Pathway.from_dict(doc)
