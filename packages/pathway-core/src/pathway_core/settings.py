"""Task policies the designer sets (DES-04): deadline and escalation, retries, undo, duration.

They are stored loosely in ``Node.settings`` so the editor can save half-finished work.
``settings_issues`` says what is wrong before Publish (the Verifier reports each one), and
the typed accessors give the Engine and the Simulator checked values to run with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TypeGuard

from pathway_core.model import Node

DISTRIBUTIONS = {
    "fixed": ("meanMin",),
    "exponential": ("meanMin",),
    "lognormal": ("meanMin", "sdMin"),
    "triangular": ("minMin", "modeMin", "maxMin"),
}
MAX_RETRIES = 10
EVENT_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{2,63}$")
MAX_RETRY_DELAY_S = 3600
DEFAULT_TIMEOUT_S = 30.0  # NFR-ROB-01: service and ML tasks
MAX_TIMEOUT_S = 3600


@dataclass(frozen=True)
class Escalation:
    role: str
    after_min: float  # how long this level has before the task escalates further


@dataclass(frozen=True)
class Deadline:
    minutes: float
    escalation: tuple[Escalation, ...]


@dataclass(frozen=True)
class Retry:
    max: int  # retries after the first attempt: max=2 means at most 3 attempts
    base_delay_s: float
    timeout_s: float = 30.0  # no answer within this time counts as a temporary failure

    def delay(self, attempt: int) -> float:
        """Exponential backoff: base, 2×base, 4×base, … for attempts 1, 2, 3, …"""
        return float(self.base_delay_s * 2 ** (attempt - 1))


@dataclass(frozen=True)
class Duration:
    dist: str
    params: dict[str, float]


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


# ---- validation ---------------------------------------------------------------


def settings_issues(node: Node) -> list[str]:
    """Everything wrong with a node's settings, in words a designer understands."""
    if node.type == "timer":
        ok = _number(node.minutes) and node.minutes is not None and node.minutes > 0
        return [] if ok else ["A timer needs a wait of more than 0 minutes"]
    if node.type == "end":
        return _emit_issues(node.settings.get("emit"))
    if node.type != "task":
        return []
    s = node.settings
    return [
        *_who_issues(node),
        *_deadline_issues(s.get("deadline")),
        *_retry_issues(node, s.get("retry")),
        *_undo_issues(s.get("undo")),
        *_duration_issues(s.get("duration")),
        *_override_issues(node, s.get("override")),
    ]


def _emit_issues(emit: Any) -> list[str]:
    """An End may announce an event (e.g. TriageCompleted) that starts another pathway."""
    if emit is None or (isinstance(emit, str) and EVENT_NAME.match(emit)):
        return []
    return [
        "An emitted event needs a name like TriageCompleted (letters and digits, starting with a capital)"
    ]


def _override_issues(node: Node, o: Any) -> list[str]:
    """WRK-02: a person may change a suggestion (e.g. the ML urgency) only with a reason."""
    if o is None:
        return []
    if (
        not isinstance(o, dict)
        or o.get("suggested") not in node.inputs
        or o.get("decided") not in node.outputs
    ):
        return [
            "An override check needs a suggested value among the inputs and a decided value among the outputs"
        ]
    return []


def _who_issues(node: Node) -> list[str]:
    if node.kind == "human" and not (node.role or "").strip():
        return ["A human task needs the role that does it"]
    if node.kind in ("service", "ml") and not (node.service or "").strip():
        return [f"A{'n ML' if node.kind == 'ml' else ' service'} task needs the service that does it"]
    return []


def _deadline_issues(d: Any) -> list[str]:
    if d is None:
        return []
    if not isinstance(d, dict) or not _number(d.get("minutes")) or d["minutes"] <= 0:
        return ["A deadline needs more than 0 minutes"]
    issues = []
    for i, step in enumerate(d.get("escalation", []), start=1):
        if not isinstance(step, dict) or not str(step.get("role", "")).strip():
            issues.append(f"Escalation level {i} needs a role")
        elif not _number(step.get("afterMin")) or step["afterMin"] <= 0:
            issues.append(f"Escalation level {i} needs a wait of more than 0 minutes")
    return issues


def _retry_issues(node: Node, r: Any) -> list[str]:
    if r is None:
        return []
    if node.kind == "human":
        return ["Retries apply to service and ML tasks; people get deadlines and escalation instead"]
    if not isinstance(r, dict) or not isinstance(r.get("max"), int) or not 1 <= r["max"] <= MAX_RETRIES:
        return [f"Retries need a maximum between 1 and {MAX_RETRIES}"]
    delay = r.get("baseDelayS")
    if not _number(delay) or not 0 < delay <= MAX_RETRY_DELAY_S:
        return [f"The first retry delay must be more than 0 and at most {MAX_RETRY_DELAY_S} seconds"]
    timeout = r.get("timeoutS", DEFAULT_TIMEOUT_S)
    if not _number(timeout) or not 0 < timeout <= MAX_TIMEOUT_S:
        return [f"The answer timeout must be more than 0 and at most {MAX_TIMEOUT_S} seconds"]
    return []


def _undo_issues(u: Any) -> list[str]:
    if u is None or (isinstance(u, str) and u.strip()):
        return []
    return ["An undo action needs the name of the service call that reverses this step"]


def _duration_issues(d: Any) -> list[str]:
    if d is None:
        return []
    if not isinstance(d, dict) or d.get("dist") not in DISTRIBUTIONS:
        return [f"A duration needs a distribution: {', '.join(DISTRIBUTIONS)}"]
    missing = [k for k in DISTRIBUTIONS[d["dist"]] if not _number(d.get(k)) or d[k] < 0]
    if missing:
        return [f"A {d['dist']} duration needs {', '.join(missing)} (minutes, not negative)"]
    return _duration_shape_issues(d)


def _duration_shape_issues(d: dict[str, Any]) -> list[str]:
    """The parameters are numbers; check they describe a real distribution."""
    if d["dist"] == "triangular":
        ordered = d["minMin"] <= d["modeMin"] <= d["maxMin"] and d["minMin"] < d["maxMin"]
        return [] if ordered else ["A triangular duration needs min ≤ mode ≤ max, with min < max"]
    return [] if d["meanMin"] > 0 else ["A duration's mean must be more than 0 minutes"]


# ---- typed accessors (for the Engine and the Simulator) -----------------------


def deadline(node: Node) -> Deadline | None:
    d = node.settings.get("deadline")
    if d is None:
        return None
    steps = tuple(Escalation(s["role"], float(s["afterMin"])) for s in d.get("escalation", []))
    return Deadline(float(d["minutes"]), steps)


def retry(node: Node) -> Retry | None:
    r = node.settings.get("retry")
    if r is None:
        return None
    return Retry(int(r["max"]), float(r["baseDelayS"]), float(r.get("timeoutS", DEFAULT_TIMEOUT_S)))


def response_timeout(node: Node) -> float | None:
    """NFR-ROB-01: how long the engine waits for a service or ML task to answer before it
    counts the silence as a temporary failure (retry, then fallback). Only for tasks that
    have somewhere to go: a retry policy or a fallback. People get deadlines instead."""
    if node.type != "task" or node.kind == "human":
        return None
    policy = retry(node)
    if policy:
        return policy.timeout_s
    return DEFAULT_TIMEOUT_S if node.fallback else None


def undo(node: Node) -> str | None:
    u = node.settings.get("undo")
    return str(u) if u else None


def emit(node: Node) -> str | None:
    """The event an End announces when the case finishes there, if any."""
    e = node.settings.get("emit")
    return str(e) if e else None


@dataclass(frozen=True)
class Override:
    suggested: str  # an input, e.g. urgency (the model's suggestion)
    decided: str  # an output, e.g. confirmed_urgency (the person's decision)


def override(node: Node) -> Override | None:
    o = node.settings.get("override")
    return None if o is None else Override(str(o["suggested"]), str(o["decided"]))


def duration(node: Node) -> Duration | None:
    d = node.settings.get("duration")
    if d is None:
        return None
    return Duration(d["dist"], {k: float(d[k]) for k in DISTRIBUTIONS[d["dist"]]})
