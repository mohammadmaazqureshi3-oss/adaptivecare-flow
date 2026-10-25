"""A simulation scenario (plan Section 8) and the readiness check for a pathway (DES-06).

Times are in minutes inside the simulator; the scenario speaks in hours and days where
that is how people think about them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pathway_core import Pathway
from pathway_core.conditions import names, parse
from pathway_core.settings import duration, settings_issues

# Illustrative urgency mix (levels 1..5) until ML-01 (Sprint 6) measures the KTAS dataset's.
DEFAULT_URGENCY_MIX = {1: 0.03, 2: 0.17, 3: 0.40, 4: 0.30, 5: 0.10}
PROB_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Target:
    """E.g. "at most 5% of urgency 1–2 patients wait more than 5 minutes for confirmation"."""

    task: str
    max_wait_min: float
    max_share: float
    urgency_max: int | None = None

    @property
    def metric(self) -> str:
        who = f"u<={self.urgency_max}" if self.urgency_max is not None else "all"
        return f"target[{self.task},{who},wait>{self.max_wait_min:g}]"

    def describe(self) -> str:
        who = f"urgency 1–{self.urgency_max} patients" if self.urgency_max is not None else "patients"
        return (
            f"at most {self.max_share:.0%} of {who} wait more than {self.max_wait_min:g} min for {self.task}"
        )


@dataclass(frozen=True)
class Scenario:
    arrivals_per_hour: tuple[float, ...]  # 24 values, hour 0..23
    staff: dict[str, int]
    cost: dict[str, float] = field(default_factory=dict)
    urgency_mix: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_URGENCY_MIX))
    days: float = 7.0
    warmup_days: float = 1.0
    targets: tuple[Target, ...] = ()
    seed: int = 1

    @property
    def horizon_min(self) -> float:
        return self.days * 24 * 60

    @property
    def warmup_min(self) -> float:
        return self.warmup_days * 24 * 60

    def with_staff(self, staff: dict[str, int]) -> Scenario:
        return replace(self, staff=dict(staff))

    def cost_of(self, staff: dict[str, int]) -> float:
        return sum(n * self.cost.get(role, 1.0) for role, n in staff.items())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scenario:
        """Parse and check a scenario; raises ``ValueError`` with a reason a person can act on."""
        days, warmup = float(d.get("days", 7)), float(d.get("warmup_days", 1))
        if not 0 <= warmup < days:
            raise ValueError("warm-up must be shorter than the simulated length")
        return cls(
            arrivals_per_hour=_hourly(d.get("arrivals_per_hour", 6.0)),
            staff=_staff(d.get("staff", {})),
            cost={str(r): float(c) for r, c in d.get("cost", {}).items()},
            urgency_mix=_mix(d.get("urgency_mix", DEFAULT_URGENCY_MIX)),
            days=days,
            warmup_days=warmup,
            targets=tuple(Target(**t) for t in d.get("targets", [])),
            seed=int(d.get("seed", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arrivals_per_hour": list(self.arrivals_per_hour),
            "staff": self.staff,
            "cost": self.cost,
            "urgency_mix": self.urgency_mix,
            "days": self.days,
            "warmup_days": self.warmup_days,
            "targets": [vars(t) for t in self.targets],
            "seed": self.seed,
        }


def _hourly(arrivals: Any) -> tuple[float, ...]:
    hourly = tuple(float(x) for x in arrivals) if isinstance(arrivals, list) else (float(arrivals),) * 24
    if len(hourly) != 24 or any(x < 0 for x in hourly):
        raise ValueError("arrivals_per_hour needs one non-negative number, or 24 of them")
    return hourly


def _mix(raw: dict[Any, Any]) -> dict[int, float]:
    mix = {int(k): float(v) for k, v in raw.items()}
    if abs(sum(mix.values()) - 1) > 1e-3 or any(v < 0 for v in mix.values()):
        raise ValueError("urgency_mix must be non-negative and sum to 1")
    return mix


def _staff(raw: dict[Any, Any]) -> dict[str, int]:
    staff = {str(r): int(n) for r, n in raw.items()}
    if any(n < 0 for n in staff.values()):
        raise ValueError("staff numbers cannot be negative")
    return staff


def human_roles(p: Pathway) -> list[str]:
    return sorted({n.role for n in p.nodes if n.type == "task" and n.kind == "human" and n.role})


def readiness_issues(p: Pathway, sc: Scenario | None = None) -> list[str]:
    """DES-06: what the Simulator still needs before it can run this pathway."""
    issues = _duration_issues(p) + _decision_issues(p)
    return issues + (_scenario_issues(p, sc) if sc is not None else [])


def _duration_issues(p: Pathway) -> list[str]:
    issues = [
        f"Task '{n.label or n.id}' needs a duration distribution"
        for n in p.nodes
        if n.type == "task" and n.kind == "human" and duration(n) is None
    ]
    return issues + [
        f"{n.label or n.id}: {m}" for n in p.nodes for m in settings_issues(n) if "duration" in m
    ]


def _decision_issues(p: Pathway) -> list[str]:
    decisions = [n.id for n in p.nodes if n.type == "xor_split" and not _evaluable(p, n.id)]
    return [issue for d in decisions for issue in _probability_issues(p, d)]


def _scenario_issues(p: Pathway, sc: Scenario) -> list[str]:
    known = {n.id for n in p.nodes if n.type == "task"}
    missing_staff = [
        f"Role '{r}' has no staff number in the scenario" for r in human_roles(p) if r not in sc.staff
    ]
    return missing_staff + [
        f"Target refers to unknown task '{t.task}'" for t in sc.targets if t.task not in known
    ]


def _evaluable(p: Pathway, node_id: str) -> bool:
    """True when every branch condition reads only data the simulator samples (urgency)."""
    conds = [e.condition for e in p.outgoing(node_id) if e.condition and not e.default]
    return all(names(parse(c)) <= {"urgency"} for c in conds)


def _probability_issues(p: Pathway, node_id: str) -> list[str]:
    branches = p.outgoing(node_id)
    label = p.node(node_id).label or node_id
    if any(e.prob is None for e in branches):
        return [
            f"Decision '{label}' needs a probability on every branch "
            "(its conditions use data the Simulator does not sample)"
        ]
    total = sum(e.prob or 0 for e in branches)
    if abs(total - 1) > PROB_TOLERANCE:
        return [f"Decision '{label}': branch probabilities sum to {total:g}, not 1"]
    return []
