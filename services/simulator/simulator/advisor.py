"""Algorithm 3, part 3 — the Staffing Advisor (SIM-03).

Greedy search, as plan Section 8 describes: start with one person per role; while some
deadline target is not met at the upper end of its 95% interval, try one more person in
each role and keep the change with the largest reduction in target shortfall per unit
of cost (common random numbers make the comparison fair). Stop when every target is met,
or when the next person would exceed the budget.

It is a heuristic: it finds a good staffing, not a proven optimum. ``exhaustive`` gives
the optimum on small cases so the report can state the measured gap.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from pathway_core import Pathway

from simulator.scenario import Scenario, Target, human_roles
from simulator.stats import Estimate, Result, replicate

ADVISOR_REPS = 10  # fixed replications per candidate; the recommendation is re-run adaptively
MAX_ROUNDS = 60
NO_DATA = Estimate(0.0, 0.0, 0.0, 0.0, 0)


def shortfall(result: Result, targets: tuple[Target, ...]) -> float:
    """How far the targets are from being met, at the upper end of each interval."""
    return sum(max(0.0, result.upper(t.metric) - t.max_share) / max(t.max_share, 1e-3) for t in targets)


def meets(result: Result, targets: tuple[Target, ...]) -> bool:
    return all(result.upper(t.metric) <= t.max_share for t in targets)


@dataclass
class Advice:
    staff: dict[str, int]
    cost: float
    feasible: bool
    rounds: list[dict[str, Any]] = field(default_factory=list)
    result: Result | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "staff": self.staff,
            "cost": self.cost,
            "feasible": self.feasible,
            "reason": self.reason,
            "rounds": self.rounds,
            "result": self.result.to_dict() if self.result else None,
        }


def advise(p: Pathway, sc: Scenario, budget: float, reps: int = ADVISOR_REPS) -> Advice:
    roles = human_roles(p)
    staff = {r: 1 for r in roles}
    rounds: list[dict[str, Any]] = []
    for _ in range(MAX_ROUNDS):
        res = replicate(p, sc.with_staff(staff), adaptive=False, reps=reps)
        rounds.append(
            {"staff": dict(staff), "cost": sc.cost_of(staff), "shortfall": shortfall(res, sc.targets)}
        )
        if meets(res, sc.targets):
            final = replicate(p, sc.with_staff(staff))  # report it with adaptive precision
            return Advice(dict(staff), sc.cost_of(staff), True, rounds, final, "every target met")
        best = _best_addition(p, sc, staff, res, roles, reps)
        staff[best] += 1
        if sc.cost_of(staff) > budget:
            staff[best] -= 1
            return Advice(
                dict(staff),
                sc.cost_of(staff),
                False,
                rounds,
                res,
                "no staffing within the budget meets every target",
            )
    return Advice(dict(staff), sc.cost_of(staff), False, rounds, None, f"stopped after {MAX_ROUNDS} rounds")


def _best_addition(
    p: Pathway, sc: Scenario, staff: dict[str, int], res: Result, roles: list[str], reps: int
) -> str:
    """The role whose extra person reduces the shortfall most per unit cost; the busiest
    role when no single addition helps yet (e.g. every role is still overloaded)."""
    base = shortfall(res, sc.targets)
    gains = {}
    for role in roles:
        trial = {**staff, role: staff[role] + 1}
        trial_res = replicate(p, sc.with_staff(trial), adaptive=False, reps=reps)
        gains[role] = (base - shortfall(trial_res, sc.targets)) / sc.cost.get(role, 1.0)
    best = max(roles, key=lambda r: gains[r])
    if gains[best] > 0:
        return best
    return max(roles, key=lambda r: res.estimates.get(f"utilisation[{r}]", NO_DATA).mean)


def exhaustive(
    p: Pathway, sc: Scenario, max_per_role: int, reps: int = ADVISOR_REPS
) -> tuple[dict[str, int], float] | None:
    """The cheapest staffing (up to ``max_per_role`` each) meeting every target: the optimum
    the greedy search is compared with on small cases."""
    roles = human_roles(p)
    best: tuple[dict[str, int], float] | None = None
    for combo in itertools.product(range(1, max_per_role + 1), repeat=len(roles)):
        staff = dict(zip(roles, combo, strict=True))
        cost = sc.cost_of(staff)
        if best is not None and cost >= best[1]:
            continue
        if meets(replicate(p, sc.with_staff(staff), adaptive=False, reps=reps), sc.targets):
            best = (staff, cost)
    return best
