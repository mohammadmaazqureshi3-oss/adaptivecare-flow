"""Algorithm 3, part 1 — discrete-event simulation of one pathway under load (plan Section 8).

One replication: virtual patients arrive (time-varying rate, by thinning), move through
the pathway with the SAME token rules as the Verifier and the Engine (pathway-core's
``TokenGraph``), wait for staff of the drawn role in priority queues (most urgent first,
then first come), and take sampled durations. A task's token move is split in two: the
token is taken when the work starts and put on the next arrow when it ends.

Everything after the warm-up is measured: waits per role, utilisation and queue length
(time-weighted), deadline misses per task, target shares, length of stay, and the number
of patients in the system (for the Little's-law check). All times are minutes.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pathway_core import Edge, Marking, Move, Node, Pathway, TokenGraph
from pathway_core.conditions import EvaluationError, evaluate, parse
from pathway_core.settings import Duration, deadline, duration

from simulator.scenario import Scenario, Target


class TimeAverage:
    """Integral of a step function over the measuring window [start, end]."""

    def __init__(self, start: float) -> None:
        self.start, self.value, self.since, self.area = start, 0.0, 0.0, 0.0

    def set(self, t: float, value: float) -> None:
        lo = max(self.since, self.start)
        if t > lo:
            self.area += self.value * (t - lo)
        self.value, self.since = value, t

    def mean(self, end: float) -> float:
        self.set(end, self.value)
        return self.area / (end - self.start) if end > self.start else 0.0


@dataclass
class VirtualCase:
    id: int
    arrival: float
    urgency: int
    marking: list[int]
    data: dict[str, Any]
    open_tasks: int = 0


@dataclass(order=True)
class _Waiting:
    urgency: int
    arrival: float
    seq: int
    case: VirtualCase = field(compare=False)
    node: Node = field(compare=False)
    produced: tuple[str, ...] = field(compare=False)
    requested: float = field(compare=False)


class _Pool:
    def __init__(self, size: int, start: float) -> None:
        self.size, self.busy = size, 0
        self.queue: list[_Waiting] = []
        self.busy_avg, self.queue_avg = TimeAverage(start), TimeAverage(start)


def stream(seed: int, k: int) -> random.Random:
    """A seeded, reproducible random stream for simulation (not for security)."""
    return random.Random(seed * 7919 + k)  # noqa: S311  # nosec B311


def sample(d: Duration | None, rng: random.Random) -> float:
    """Minutes for one task, from the designer's distribution (DES-06)."""
    if d is None:
        return 0.0
    p = d.params
    if d.dist == "fixed":
        return p["meanMin"]
    if d.dist == "exponential":
        return rng.expovariate(1 / p["meanMin"])
    if d.dist == "lognormal":
        sigma2 = math.log(1 + (p["sdMin"] / p["meanMin"]) ** 2)
        return rng.lognormvariate(math.log(p["meanMin"]) - sigma2 / 2, math.sqrt(sigma2))
    return rng.triangular(p["minMin"], p["maxMin"], p["modeMin"])


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Replication:
    """One run of the simulation; ``run()`` returns its metrics."""

    def __init__(self, p: Pathway, sc: Scenario, seed: int) -> None:
        self.p, self.sc = p, sc
        self.g = TokenGraph(p)
        self.nodes = {n.id: n for n in p.nodes}
        # Separate streams keep common random numbers aligned across staffing levels.
        self.rng_arrivals, self.rng_work, self.rng_routing = (stream(seed, k) for k in (1, 2, 3))
        self.fel: list[tuple[float, int, str, Any]] = []
        self.seq = 0
        self.t = 0.0
        w = sc.warmup_min
        self.pools = {r: _Pool(n, w) for r, n in sc.staff.items()}
        self.in_system = TimeAverage(w)
        self.active = 0
        self.waits: dict[str, list[float]] = defaultdict(list)
        self.task_waits: dict[tuple[str, int], float] = {}  # (task node, case id) -> first wait
        self.deadline_total: dict[str, int] = defaultdict(int)
        self.deadline_missed: dict[str, int] = defaultdict(int)
        self.stays: list[float] = []
        self.arrived_in_window = 0
        self.cases: dict[int, VirtualCase] = {}  # cases still in the system
        self.urgencies: dict[int, int] = {}  # every case's urgency, for the target metrics
        self.next_id = 0
        self.conditions = {e.id: parse(e.condition) for e in p.edges if e.condition}
        self.peak = max(sc.arrivals_per_hour)
        self.urgency_levels = sorted(sc.urgency_mix)
        self.urgency_weights = [sc.urgency_mix[u] for u in self.urgency_levels]

    # ---- the event loop (plan Section 8) -----------------------------------------------

    def push(self, t: float, kind: str, payload: Any) -> None:
        self.seq += 1
        heapq.heappush(self.fel, (t, self.seq, kind, payload))  # ties broken by insertion order

    def run(self) -> dict[str, float]:
        if self.peak > 0:
            self.push(self.next_arrival(0.0), "arrival", None)
        horizon = self.sc.horizon_min
        while self.fel and self.fel[0][0] < horizon:
            self.t, _, kind, payload = heapq.heappop(self.fel)
            if kind == "arrival":
                self.arrive()
                self.push(self.next_arrival(self.t), "arrival", None)
            else:
                self.task_end(*payload)
        return self.metrics()

    def next_arrival(self, t: float) -> float:
        """Thinning: candidates at the peak rate, each kept with probability rate(t)/peak."""
        while True:
            t += self.rng_arrivals.expovariate(self.peak / 60)
            rate = self.sc.arrivals_per_hour[int(t // 60) % 24]
            if self.rng_arrivals.random() * self.peak <= rate:
                return t

    def arrive(self) -> None:
        urgency = self.rng_arrivals.choices(self.urgency_levels, self.urgency_weights)[0]
        case = VirtualCase(
            self.next_id, self.t, urgency, list(self.g.initial_marking()), {"urgency": urgency}
        )
        self.next_id += 1
        self.cases[case.id] = case
        self.urgencies[case.id] = urgency
        self.active += 1
        self.in_system.set(self.t, self.active)
        if self.t >= self.sc.warmup_min:
            self.arrived_in_window += 1
        self.advance(case)

    # ---- token rules for a virtual case ----------------------------------------------------

    def advance(self, case: VirtualCase) -> None:
        """Fire every instant move; start every task or timer that became enabled."""
        while (mv := self._next_move(case)) is not None:
            self._fire(case, mv)
        if not any(case.marking) and case.open_tasks == 0:
            self.complete(case)

    def _next_move(self, case: VirtualCase) -> Move | None:
        """Instant moves first (decisions, merges, splits, joins, ends), then work to start."""
        marking: Marking = tuple(case.marking)
        moves = [mv for mv in self.g.enabled_moves(marking) if not self._is_fallback(mv)]
        if not moves:
            return None
        instant = [mv for mv in moves if self.nodes[mv.node].type not in ("task", "timer")]
        return self.choose(case, instant) if instant else moves[0]

    def _fire(self, case: VirtualCase, mv: Move) -> None:
        for edge in mv.consumed:
            case.marking[self.g.index[edge]] -= 1
        node = self.nodes[mv.node]
        if node.type in ("task", "timer"):  # the token is taken now and put on when the work ends
            case.open_tasks += 1
            self.start_work(case, node, mv.produced)
        else:
            self._produce(case, mv.produced)

    def _is_fallback(self, mv: Move) -> bool:
        return any(self.g.edges[self.g.index[e]].fallback for e in mv.produced)

    def choose(self, case: VirtualCase, instant: list[Move]) -> Move:
        """A decision takes one branch: by its conditions when they only need sampled data
        (urgency), otherwise by the branch probabilities the designer set (DES-06)."""
        first = instant[0]
        if self.nodes[first.node].type != "xor_split":
            return first
        options = [mv for mv in instant if mv.node == first.node and mv.consumed == first.consumed]
        edges = [self.g.edges[self.g.index[mv.produced[0]]] for mv in options]
        try:
            return self._by_conditions(case, options, edges)
        except EvaluationError:  # the condition reads data the simulation does not have
            return self.rng_routing.choices(options, [e.prob or 0.0 for e in edges])[0]

    def _by_conditions(self, case: VirtualCase, options: list[Move], edges: list[Edge]) -> Move:
        """Rule 3: the first branch whose condition holds, otherwise the default."""
        pairs = list(zip(options, edges, strict=True))
        chosen = next(
            (mv for mv, e in pairs if not e.default and evaluate(self.conditions[e.id], case.data)), None
        )
        return chosen or next(mv for mv, e in pairs if e.default)

    def _produce(self, case: VirtualCase, produced: tuple[str, ...]) -> None:
        for edge in produced:
            case.marking[self.g.index[edge]] += 1

    # ---- work, staff and queues ---------------------------------------------------------------

    def start_work(self, case: VirtualCase, node: Node, produced: tuple[str, ...]) -> None:
        if node.type == "timer":
            self.push(self.t + (node.minutes or 0), "task_end", (case.id, node.id, produced, None, self.t))
            return
        pool = self.pools.get(node.role or "") if node.kind == "human" else None
        if pool is None:  # services and the ML model: no staff, no queue
            self.push(
                self.t + sample(duration(node), self.rng_work),
                "task_end",
                (case.id, node.id, produced, None, self.t),
            )
            return
        item = _Waiting(case.urgency, case.arrival, self.seq, case, node, produced, self.t)
        self.seq += 1
        if pool.busy < pool.size:
            self.begin(pool, item)
        else:
            heapq.heappush(pool.queue, item)
            pool.queue_avg.set(self.t, len(pool.queue))

    def begin(self, pool: _Pool, item: _Waiting) -> None:
        pool.busy += 1
        pool.busy_avg.set(self.t, pool.busy)
        wait = self.t - item.requested
        if item.requested >= self.sc.warmup_min:
            self.waits[item.node.role or ""].append(wait)
            self.task_waits.setdefault((item.node.id, item.case.id), wait)
        end = self.t + sample(duration(item.node), self.rng_work)
        self.push(
            end, "task_end", (item.case.id, item.node.id, item.produced, item.node.role, item.requested)
        )

    def task_end(
        self, case_id: int, node_id: str, produced: tuple[str, ...], role: str | None, requested: float
    ) -> None:
        case = self.cases[case_id]
        node = self.nodes[node_id]
        if role is not None:
            pool = self.pools[role]
            pool.busy -= 1
            pool.busy_avg.set(self.t, pool.busy)
            if pool.queue:  # hand over to the next queued patient, most urgent first
                nxt = heapq.heappop(pool.queue)
                pool.queue_avg.set(self.t, len(pool.queue))
                self.begin(pool, nxt)
        chain = deadline(node)
        if chain and requested >= self.sc.warmup_min:
            self.deadline_total[node_id] += 1
            if self.t - requested > chain.minutes:
                self.deadline_missed[node_id] += 1
        case.open_tasks -= 1
        self._produce(case, produced)
        self.advance(case)

    def complete(self, case: VirtualCase) -> None:
        self.active -= 1
        self.in_system.set(self.t, self.active)
        if case.arrival >= self.sc.warmup_min:
            self.stays.append(self.t - case.arrival)
        del self.cases[case.id]

    # ---- metrics --------------------------------------------------------------------------------

    def metrics(self) -> dict[str, float]:
        end = self.sc.horizon_min
        window_min = end - self.sc.warmup_min
        out: dict[str, float] = {}
        for role, pool in self.pools.items():
            out |= self._role_metrics(role, pool, end)
        for node_id, total in self.deadline_total.items():
            out[f"deadline_miss[{node_id}]"] = self.deadline_missed[node_id] / total
        for target in self.sc.targets:
            out[target.metric] = self._target_share(target)
        out["los_mean"] = _mean(self.stays)
        out["in_system"] = self.in_system.mean(end)
        out["arrival_rate_per_min"] = self.arrived_in_window / window_min if window_min > 0 else 0.0
        out["completed"] = float(len(self.stays))
        return out

    def _role_metrics(self, role: str, pool: _Pool, end: float) -> dict[str, float]:
        waits = self.waits.get(role, [])
        return {
            f"wait_mean[{role}]": _mean(waits),
            f"wait_p95[{role}]": percentile(waits, 0.95),
            f"utilisation[{role}]": pool.busy_avg.mean(end) / pool.size if pool.size else 0.0,
            f"queue[{role}]": pool.queue_avg.mean(end),
        }

    def _target_share(self, target: Target) -> float:
        """Share of the patients the target names whose wait for its task exceeded the limit."""
        waits = [
            w
            for (node_id, cid), w in self.task_waits.items()
            if node_id == target.task
            and (target.urgency_max is None or self.urgencies[cid] <= target.urgency_max)
        ]
        return sum(1 for w in waits if w > target.max_wait_min) / len(waits) if waits else 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def simulate(p: Pathway, sc: Scenario, seed: int) -> dict[str, float]:
    """One replication with ``seed``; returns its metrics."""
    return Replication(p, sc, seed).run()
