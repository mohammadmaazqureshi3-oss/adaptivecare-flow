"""Simulated task services for engine tests: they answer every request like real workers would.

Answers are a pure function of (case, node), so two runs of the same cases give the same
data whatever the delivery order, which lets tests compare a faulty run with a clean one.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from care_events import Bus, Event
from pathway_core import Pathway

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"


def load(name: str) -> Pathway:
    return Pathway.from_dict(json.loads((PATHWAYS / f"{name}.json").read_text()))


def _n(*parts: object) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest(), 16)


def value_for(var_type: str, seed: int) -> Any:
    if var_type == "int":
        return seed % 5 + 1 if seed % 7 else 85 + seed % 15  # urgency 1..5, sometimes an spo2-like value
    if var_type == "float":
        return round((seed % 100) / 100, 2)
    if var_type == "bool":
        return seed % 2 == 0
    return f"v{seed % 1000}"


def answer(request: Event, fail_ml: bool = True) -> Event:
    """The reply a worker would send for ``request``."""
    p = request.payload
    if fail_ml and p.get("kind") == "ml":
        return request.reply("TaskFailed", {"reason": "model not available", "temporary": False})
    outputs = {
        o["name"]: value_for(o["type"], _n(request.case_id, p["node"], o["name"])) for o in p["outputs"]
    }
    if "spo2" in outputs:
        outputs["spo2"] = 80 + _n(request.case_id, "spo2") % 20
    return request.reply("TaskCompleted", {"outputs": outputs})


class FakeWorkers:
    """Subscribes to every TaskRequested and answers it."""

    def __init__(self, bus: Bus, fail_ml: bool = True) -> None:
        self.bus = bus
        self.fail_ml = fail_ml
        self.requests: list[Event] = []
        self._lock = threading.Lock()
        bus.subscribe("fake-workers", ["TaskRequested.#"], self.on_event)

    def on_event(self, request: Event) -> None:
        with self._lock:
            self.requests.append(request)
        self.bus.publish(answer(request, self.fail_ml))
