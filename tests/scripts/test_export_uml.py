"""The PlantUML exporter (U28–U30): structured blocks, each step written exactly once."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from export_uml import export
from pathway_core import Pathway

ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> Pathway:
    return Pathway.from_dict(json.loads((ROOT / path).read_text()))


@pytest.mark.parametrize("name", ["triage", "assessment", "visit"])
def test_every_task_appears_exactly_once(name: str) -> None:
    p = load(f"pathways/clinical/{name}.json")
    text = export(p, "U99")
    for n in p.nodes:
        if n.type == "task":
            assert text.count(f":{n.label}\\n") == 1, n.label
    assert text.startswith(f"@startuml U99_{p.id}_pathway_activity") and text.rstrip().endswith("@enduml")


def test_parallel_block_closes_before_the_review_and_events_are_noted() -> None:
    text = export(load("pathways/clinical/assessment.json"), "U29")
    assert text.index("end fork") < text.index(":Doctor review")
    assert "started by **TriageCompleted**" in text and "announces **AdmissionRequested**" in text


def test_fallback_lane_and_settings_notes() -> None:
    text = export(load("pathways/clinical/triage.json"), "U28")
    assert 'partition "fallback: Manual triage' in text and "retries 2× from 1 s" in text
    assert "changing urgency → confirmed_urgency needs a reason" in text
    assert text.count("endif") == 1 and text.index("endif") < text.index(":Triage complete")
