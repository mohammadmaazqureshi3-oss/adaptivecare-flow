"""Algorithm 3: the simulation itself (SIM-01, DES-06) and its statistics (SIM-02)."""

from __future__ import annotations

import random
import statistics

import pytest
from models import single_queue, triage
from pathway_core import Pathway
from pathway_core.settings import Duration
from simulator.des import Replication, percentile, sample, simulate
from simulator.scenario import Scenario, readiness_issues
from simulator.stats import confidence_interval, replicate


def scenario(**over: object) -> Scenario:
    base: dict[str, object] = {"arrivals_per_hour": 6, "staff": {"nurse": 2}, "days": 4, "warmup_days": 1}
    return Scenario.from_dict({**base, **over})


# ---- DES-06: readiness ------------------------------------------------------------------


def test_des06_triage_is_ready_to_simulate() -> None:
    assert readiness_issues(triage(), scenario()) == []


def test_des06_missing_durations_and_probabilities_are_listed() -> None:
    doc = triage().to_dict()
    for n in doc["nodes"]:
        if n["id"] == "vitals":
            del n["duration"]
    for e in doc["edges"]:
        e.pop("prob", None)
    issues = readiness_issues(Pathway.from_dict(doc), scenario(staff={}))
    text = "\n".join(issues)
    assert "Measure vital signs' needs a duration" in text
    assert "needs a probability on every branch" in text
    assert "Role 'nurse' has no staff number" in text


def test_des06_probabilities_must_sum_to_one() -> None:
    doc = triage().to_dict()
    for e in doc["edges"]:
        if e.get("prob") == 0.7:
            e["prob"] = 0.6
    assert any("sum to 0.9" in i for i in readiness_issues(Pathway.from_dict(doc)))


def test_conditions_on_urgency_alone_need_no_probabilities() -> None:
    doc = triage().to_dict()
    for e in doc["edges"]:
        e.pop("prob", None)
        if e.get("condition"):
            e["condition"] = "urgency <= 2"
    assert readiness_issues(Pathway.from_dict(doc)) == []


@pytest.mark.parametrize(
    "bad", [{"arrivals_per_hour": [1, 2]}, {"urgency_mix": {"1": 0.5}}, {"warmup_days": 9}]
)
def test_invalid_scenarios_are_rejected(bad: dict) -> None:
    with pytest.raises(ValueError):
        scenario(**bad)


# ---- the simulation loop ---------------------------------------------------------------------


def test_sim01_triage_run_reports_waits_utilisation_and_deadline_misses() -> None:
    m = simulate(
        triage(),
        scenario(targets=[{"task": "confirm", "max_wait_min": 5, "max_share": 0.05, "urgency_max": 2}]),
        1,
    )
    for key in (
        "wait_mean[nurse]",
        "wait_p95[nurse]",
        "utilisation[nurse]",
        "queue[nurse]",
        "deadline_miss[vitals]",
        "target[confirm,u<=2,wait>5]",
        "los_mean",
        "in_system",
    ):
        assert key in m
    # vitals ≈ 6 min + confirm/waiting ≈ 2.3 min of nurse work per patient, 0.1 patients/min, 2 nurses
    assert 0.35 < m["utilisation[nurse]"] < 0.48
    assert 0.09 < m["arrival_rate_per_min"] < 0.11


def test_same_seed_same_result_different_seed_different_result() -> None:
    p, sc = triage(), scenario()
    assert simulate(p, sc, 7) == simulate(p, sc, 7)
    assert simulate(p, sc, 7) != simulate(p, sc, 8)


def test_thinning_follows_the_hourly_rates() -> None:
    hourly = [0.0] * 12 + [12.0] * 12  # nobody comes at night
    rep = Replication(single_queue(1), scenario(arrivals_per_hour=hourly, days=20, warmup_days=0), 3)
    times, t = [], 0.0
    for _ in range(2000):
        t = rep.next_arrival(t)
        times.append(t)
    assert all((x // 60) % 24 >= 12 for x in times)  # none in the quiet hours
    per_busy_hour = len(times) / (times[-1] / 60 / 2)
    assert 11 < per_busy_hour < 13


def test_most_urgent_patient_is_seen_first() -> None:
    """Priority queues: with one busy nurse (utilisation 0.9), urgency-1 patients wait far less."""
    sc = scenario(arrivals_per_hour=10.8, staff={"nurse": 1}, urgency_mix={"1": 0.2, "5": 0.8}, days=10)
    rep = Replication(single_queue(5), sc, 2)
    rep.run()
    by_level: dict[int, list[float]] = {1: [], 5: []}
    for (_, case_id), wait in rep.task_waits.items():
        by_level[rep.urgencies[case_id]].append(wait)
    urgent, others = statistics.fmean(by_level[1]), statistics.fmean(by_level[5])
    assert urgent < others / 3, (urgent, others)


def test_parallel_branches_and_joins_follow_the_token_rules() -> None:
    m = simulate(triage(), scenario(staff={"nurse": 50}), 4)
    assert m["wait_mean[nurse]"] == 0.0  # plenty of staff: nobody waits
    # length of stay = max(predict, vitals) + confirm-or-waiting: about 6 + 2.3 minutes
    assert 7 < m["los_mean"] < 10


def test_duration_sampling_matches_the_designer_distributions() -> None:
    rng = random.Random(0)
    logn = [sample(Duration("lognormal", {"meanMin": 6, "sdMin": 2}), rng) for _ in range(20000)]
    assert abs(statistics.fmean(logn) - 6) < 0.1 and abs(statistics.stdev(logn) - 2) < 0.1
    tri = [
        sample(Duration("triangular", {"minMin": 1, "modeMin": 2, "maxMin": 4}), rng) for _ in range(20000)
    ]
    assert min(tri) >= 1 and max(tri) <= 4 and abs(statistics.fmean(tri) - 7 / 3) < 0.05
    assert sample(Duration("fixed", {"meanMin": 3}), rng) == 3 and sample(None, rng) == 0
    assert percentile([1, 2, 3, 4], 0.5) == 2.5 and percentile([], 0.9) == 0


# ---- SIM-02: replications and intervals ----------------------------------------------------------


def test_confidence_interval_formula() -> None:
    e = confidence_interval([10.0, 12.0, 11.0, 13.0, 9.0])
    # t(4, 0.975) = 2.776, s = 1.581, n = 5 → half-width 1.963
    assert e.mean == 11 and abs(e.half_width - 1.963) < 0.001 and e.low < 11 < e.high


def test_sim02_every_metric_has_an_interval_precise_enough_or_the_cap_is_reported() -> None:
    res = replicate(triage(), scenario(days=3))
    assert 10 <= res.replications <= 100
    for name in ("wait_mean[nurse]", "utilisation[nurse]", "los_mean"):
        e = res.estimates[name]
        assert e.low <= e.mean <= e.high
        assert res.cap_reached or e.half_width <= 0.05 * abs(e.mean) or e.half_width <= 0.25


def test_noisy_scenario_reports_the_cap() -> None:
    res = replicate(triage(), scenario(days=0.3, warmup_days=0.05), max_reps=12)
    assert res.replications == 12 and res.cap_reached


# ---- plan Section 11: the urgency mix comes from the model's training data -----------------------


def test_default_urgency_mix_is_the_training_datas() -> None:
    import json
    from pathlib import Path

    from simulator.scenario import DEFAULT_URGENCY_MIX, URGENCY_MIX_SOURCE

    counts = json.loads((Path(__file__).parents[3] / "docs" / "ml" / "metrics.json").read_text())[
        "class_counts"
    ]
    total = sum(counts.values())
    assert abs(sum(DEFAULT_URGENCY_MIX.values()) - 1) < 1e-9
    for level, n in counts.items():
        assert abs(DEFAULT_URGENCY_MIX[int(level)] - n / total) < 1e-3
    assert URGENCY_MIX_SOURCE.startswith("synthetic-v1")  # until the KTAS file is used


def test_without_the_mix_file_the_illustrative_mix_is_used(tmp_path: object) -> None:
    from pathlib import Path

    from simulator.scenario import ILLUSTRATIVE_MIX, load_default_mix

    mix, source = load_default_mix(Path(str(tmp_path)) / "absent.json")
    assert mix == ILLUSTRATIVE_MIX and source.startswith("illustrative")
