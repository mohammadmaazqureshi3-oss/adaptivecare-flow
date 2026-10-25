"""SIM-03: the cheapest staffing that meets every deadline target, and how close greedy gets."""

from __future__ import annotations

from models import two_roles
from simulator.advisor import advise, exhaustive, meets, shortfall
from simulator.scenario import Scenario
from simulator.stats import replicate

TARGETS = [
    {"task": "assess", "max_wait_min": 10, "max_share": 0.10},
    {"task": "review", "max_wait_min": 15, "max_share": 0.10},
]


def scenario(**over: object) -> Scenario:
    base: dict[str, object] = {
        "arrivals_per_hour": 8,
        "staff": {"nurse": 1, "doctor": 1},
        "cost": {"nurse": 1.0, "doctor": 2.5},
        "days": 4,
        "warmup_days": 1,
        "targets": TARGETS,
    }
    return Scenario.from_dict({**base, **over})


def test_sim03_recommendation_meets_every_target_at_the_upper_end_of_its_interval() -> None:
    advice = advise(two_roles(), scenario(), budget=50)
    assert advice.feasible and advice.result is not None
    for t in scenario().targets:
        assert advice.result.upper(t.metric) <= t.max_share, t.describe()
    assert advice.staff["nurse"] >= 2 and advice.staff["doctor"] >= 2  # 1 each is overloaded (λ·S > 1)
    assert advice.rounds[0]["staff"] == {"doctor": 1, "nurse": 1}
    assert advice.rounds[-1]["shortfall"] == 0


def test_sim03_greedy_is_compared_with_exhaustive_search() -> None:
    """The plan's check on a small case: the report states the measured gap."""
    p, sc = two_roles(), scenario()
    greedy = advise(p, sc, budget=50)
    best = exhaustive(p, sc, max_per_role=5)
    assert best is not None
    gap = greedy.cost - best[1]
    assert gap >= 0  # nothing beats the optimum
    assert gap <= 2.5, f"greedy {greedy.staff} cost {greedy.cost}, optimum {best[0]} cost {best[1]}"


def test_sim03_no_staffing_within_budget_is_reported() -> None:
    advice = advise(two_roles(), scenario(), budget=4)
    assert not advice.feasible and "budget" in advice.reason
    assert advice.cost <= 4


def test_shortfall_is_zero_exactly_when_targets_are_met() -> None:
    sc = scenario(staff={"nurse": 4, "doctor": 5})
    res = replicate(two_roles(), sc, adaptive=False, reps=10)
    assert meets(res, sc.targets) and shortfall(res, sc.targets) == 0
    tight = scenario(staff={"nurse": 1, "doctor": 1})
    res = replicate(two_roles(), tight, adaptive=False, reps=10)
    assert not meets(res, tight.targets) and shortfall(res, tight.targets) > 0
