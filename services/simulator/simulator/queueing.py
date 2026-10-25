"""Exact queueing results, used only to validate the simulator (SIM-04).

    W_q = C(c, a) / (c·μ − λ),   a = λ/μ
    C(c, a) = (a^c / c! · c/(c−a)) / (Σ_{k<c} a^k/k! + a^c/c! · c/(c−a))

Real pathways have parallel steps, priorities, non-exponential durations and hourly
arrivals, for which no closed formula exists; the formula is used where it is exact.
"""

from __future__ import annotations

import math


def erlang_c(c: int, lam: float, mu: float) -> float:
    """Probability that an arrival has to wait in an M/M/c queue (requires λ < cμ)."""
    a = lam / mu
    if a >= c:
        raise ValueError("unstable queue: λ must be below c·μ")
    top = a**c / math.factorial(c) * c / (c - a)
    return top / (sum(a**k / math.factorial(k) for k in range(c)) + top)


def mmc_mean_wait(c: int, lam: float, mu: float) -> float:
    """Mean time in the queue, W_q, in the same time unit as 1/λ and 1/μ."""
    return erlang_c(c, lam, mu) / (c * mu - lam)
