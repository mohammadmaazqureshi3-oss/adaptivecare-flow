"""Algorithm 3, part 2 — independent replications and 95% confidence intervals (SIM-02).

    mean ± t(n−1, 0.975) · s / √n

Adaptive stopping: start with 10 replications and add more until every key metric's
half-width is below 5% of its mean (or below a small absolute tolerance, for metrics
near zero such as the wait of an idle role), up to 100. Seeds are 1..n offset by the
scenario seed, so two scenarios compared with the same seed use common random numbers.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pathway_core import Pathway
from scipy.stats import t as student_t

from simulator.des import simulate
from simulator.scenario import Scenario

MIN_REPS, MAX_REPS, STEP = 10, 100, 5
RELATIVE = 0.05
ABSOLUTE = {"wait": 0.25, "utilisation": 0.01, "queue": 0.05, "target": 0.005, "deadline": 0.005, "los": 0.25}


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float
    half_width: float
    n: int

    def to_dict(self) -> dict[str, float]:
        return {"mean": self.mean, "low": self.low, "high": self.high, "half_width": self.half_width}


def confidence_interval(values: list[float], level: float = 0.95) -> Estimate:
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return Estimate(mean, mean, mean, math.inf, n)
    hw = float(student_t.ppf(0.5 + level / 2, n - 1)) * statistics.stdev(values) / math.sqrt(n)
    return Estimate(mean, mean - hw, mean + hw, hw, n)


def key_metrics(metrics: dict[str, float]) -> list[str]:
    """Metrics that decide when to stop: waits, utilisation, targets, length of stay."""
    prefixes = ("wait_mean[", "utilisation[", "target[", "los_mean")
    return [k for k in metrics if k.startswith(prefixes)]


def precise_enough(name: str, e: Estimate) -> bool:
    family = name.split("_")[0].split("[")[0]
    tolerance = ABSOLUTE.get(family, 0.0)
    return e.half_width <= RELATIVE * abs(e.mean) or e.half_width <= tolerance


@dataclass(frozen=True)
class Result:
    estimates: dict[str, Estimate]
    replications: int
    cap_reached: bool

    def upper(self, metric: str) -> float:
        return self.estimates[metric].high if metric in self.estimates else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "replications": self.replications,
            "cap_reached": self.cap_reached,
            "metrics": {k: e.to_dict() for k, e in sorted(self.estimates.items())},
        }


Runner = Callable[[Pathway, Scenario, int], dict[str, float]]


def replicate(
    p: Pathway,
    sc: Scenario,
    *,
    adaptive: bool = True,
    reps: int = MIN_REPS,
    max_reps: int = MAX_REPS,
    runner: Runner = simulate,
) -> Result:
    """Run replications; with ``adaptive`` keep adding until precise enough or ``max_reps``."""
    runs: list[dict[str, float]] = []

    def run_more(k: int) -> None:
        start = len(runs)
        runs.extend(runner(p, sc, sc.seed * 100_000 + i) for i in range(start + 1, start + k + 1))

    run_more(reps)
    while adaptive:
        estimates = _estimate(runs)
        if all(precise_enough(m, estimates[m]) for m in key_metrics(runs[0])) or len(runs) >= max_reps:
            break
        run_more(min(STEP, max_reps - len(runs)))
    estimates = _estimate(runs)
    cap = (
        adaptive
        and len(runs) >= max_reps
        and not all(precise_enough(m, estimates[m]) for m in key_metrics(runs[0]))
    )
    return Result(estimates, len(runs), cap)


def _estimate(runs: list[dict[str, float]]) -> dict[str, Estimate]:
    names = sorted({k for r in runs for k in r})
    return {k: confidence_interval([r.get(k, 0.0) for r in runs]) for k in names}
