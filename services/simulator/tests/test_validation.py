"""SIM-04: the simulator is validated against queueing theory before any result is trusted.

1. M/M/c: across 100 independent experiments, the exact Erlang C mean wait falls inside the
   simulated 95% interval about 95 times; 90 or more passes.
2. Little's law: L = λW within the interval.
3. Extreme cases: no arrivals → no waits; one nurse under heavy load → waits keep growing.
Plus NFR-PERF-03: 30 replications of 7 days for a 20-node pathway in at most 60 s.
"""

from __future__ import annotations

import time

from models import single_queue
from pathway_core import Pathway
from simulator.des import simulate
from simulator.queueing import erlang_c, mmc_mean_wait
from simulator.scenario import Scenario
from simulator.stats import confidence_interval, replicate

LAMBDA_PER_H, MEAN_SERVICE_MIN, SERVERS = 8.0, 12.0, 2  # a = 1.6, utilisation 0.8


def mmc_scenario(seed: int, **over: object) -> Scenario:
    base: dict[str, object] = {
        "arrivals_per_hour": LAMBDA_PER_H,
        "staff": {"nurse": SERVERS},
        "urgency_mix": {"3": 1.0},  # one class: first come, first served
        "days": 5,
        "warmup_days": 1,
        "seed": seed,
    }
    return Scenario.from_dict({**base, **over})


def test_erlang_c_formula_on_a_textbook_case() -> None:
    # λ = 2/min, μ = 1/min, c = 3 → C = 4/9 ≈ 0.4444, Wq = 0.4444 min
    assert abs(erlang_c(3, 2.0, 1.0) - 4 / 9) < 1e-9
    assert abs(mmc_mean_wait(3, 2.0, 1.0) - 4 / 9) < 1e-9


def test_sim04_erlang_c_lies_inside_the_interval_in_at_least_90_of_100_experiments() -> None:
    exact = mmc_mean_wait(SERVERS, LAMBDA_PER_H / 60, 1 / MEAN_SERVICE_MIN)  # minutes
    p = single_queue(MEAN_SERVICE_MIN)
    covered = 0
    for experiment in range(100):
        e = replicate(p, mmc_scenario(experiment + 1), adaptive=False, reps=10).estimates["wait_mean[nurse]"]
        covered += e.low <= exact <= e.high
    assert covered >= 90, f"Erlang C W_q = {exact:.3f} min was inside only {covered}/100 intervals"


def test_sim04_littles_law_holds() -> None:
    p = single_queue(MEAN_SERVICE_MIN)
    runs = [simulate(p, mmc_scenario(9), seed) for seed in range(1, 21)]
    l_values = [r["in_system"] for r in runs]
    lw_values = [r["arrival_rate_per_min"] * r["los_mean"] for r in runs]
    diff = confidence_interval([a - b for a, b in zip(l_values, lw_values, strict=True)])
    assert diff.low <= 0 <= diff.high or abs(diff.mean) < 0.02 * confidence_interval(l_values).mean


def test_sim04_no_arrivals_means_no_waits() -> None:
    m = simulate(single_queue(5), mmc_scenario(1, arrivals_per_hour=0), 1)
    assert m["wait_mean[nurse]"] == 0 and m["utilisation[nurse]"] == 0 and m["completed"] == 0


def test_sim04_one_nurse_under_heavy_load_waits_keep_growing() -> None:
    p = single_queue(MEAN_SERVICE_MIN)
    waits = [
        simulate(p, mmc_scenario(1, staff={"nurse": 1}, days=d, warmup_days=0.5), 3)["wait_mean[nurse]"]
        for d in (1, 2, 4)
    ]
    assert waits[0] < waits[1] < waits[2]  # λ = 8/h against 5/h of capacity: no steady state


def test_nfr_perf_03_thirty_replications_of_seven_days_for_a_20_node_pathway_in_60_s() -> None:
    nodes = [
        {"id": "start", "type": "start", "trigger": "PatientRegistered"},
        {"id": "split", "type": "and_split"},
    ]
    edges = [{"from": "start", "to": "split"}]
    for b in range(3):
        prev = "split"
        for k in range(6 if b == 0 else 5):  # 16 tasks + start, split, join, end = 20 nodes
            nid = f"b{b}_{k}"
            role = ("nurse", "doctor", "porter")[b]
            nodes.append(
                {
                    "id": nid,
                    "type": "task",
                    "kind": "human",
                    "role": role,
                    "duration": {"dist": "lognormal", "meanMin": 2, "sdMin": 1},
                }
            )
            edges.append({"from": prev, "to": nid})
            prev = nid
        edges.append({"from": prev, "to": "join"})
    nodes += [{"id": "join", "type": "and_join"}, {"id": "end", "type": "end"}]
    edges.append({"from": "join", "to": "end"})
    p = Pathway.from_dict({"id": "big", "version": 1, "nodes": nodes, "edges": edges})
    assert len(p.nodes) == 20
    sc = Scenario.from_dict(
        {"arrivals_per_hour": 10, "staff": {"nurse": 3, "doctor": 3, "porter": 3}, "days": 7}
    )
    started = time.perf_counter()
    res = replicate(p, sc, adaptive=False, reps=30)
    elapsed = time.perf_counter() - started
    assert res.replications == 30
    assert elapsed < 60, f"{elapsed:.1f} s"
