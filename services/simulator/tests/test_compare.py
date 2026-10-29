"""SIM-05: as a designer, I compare two scenarios side by side."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from simulator.compare import compare_metric, direction, metrics_of, scenario_changes
from simulator.db import Database, JobRow, make_engine
from simulator.main import create_app


def est(mean: float, hw: float) -> dict[str, float]:
    return {"mean": mean, "low": mean - hw, "high": mean + hw, "half_width": hw}


@pytest.mark.parametrize(
    "metric,expected",
    [
        ("wait_mean[nurse]", "lower"),
        ("deadline_miss[vitals]", "lower"),
        ("los_mean", "lower"),
        ("target[confirm,u<=2,wait>5]", "lower"),  # share of patients beyond the limit
        ("completed", "higher"),
        ("utilisation[nurse]", None),
    ],  # fmt: skip
)
def test_sim05_which_way_is_better(metric: str, expected: str | None) -> None:
    assert direction(metric) == expected


def test_sim05_separate_intervals_name_the_better_scenario() -> None:
    row = compare_metric("wait_mean[nurse]", est(20, 3), est(8, 2))
    assert row["distinct"] and row["better"] == "b" and row["difference"] == -12
    row = compare_metric("completed", est(300, 5), est(250, 5))
    assert row["distinct"] and row["better"] == "a"


def test_sim05_fewer_patients_beyond_a_target_limit_is_better() -> None:
    # A target metric is the share of patients who waited longer than the limit (2 nurses: 1%,
    # 4 nurses: 0%), so the run with the smaller share is the better one.
    row = compare_metric("target[confirm,u<=2,wait>5]", est(0.012, 0.002), est(0.0, 0.0))
    assert row["distinct"] and row["better"] == "b" and row["better_is"] == "lower"


def test_sim05_overlapping_intervals_cannot_tell_the_scenarios_apart() -> None:
    row = compare_metric("wait_mean[nurse]", est(10, 3), est(8, 3))
    assert not row["distinct"] and row["better"] is None and row["difference"] == -2


def test_sim05_neutral_and_missing_metrics() -> None:
    assert compare_metric("utilisation[nurse]", est(0.9, 0.01), est(0.5, 0.01))["better"] is None
    row = compare_metric("wait_mean[doctor]", None, est(5, 1))
    assert row["difference"] is None and not row["distinct"]


def test_sim05_changed_settings_are_listed() -> None:
    a = {"staff": {"nurse": 2, "doctor": 1}, "arrivals_per_hour": [2.0] * 24, "days": 7, "seed": 1}
    b = {"staff": {"nurse": 3, "doctor": 1}, "arrivals_per_hour": [2.5] * 24, "days": 7, "seed": 1}
    assert scenario_changes(a, b) == [
        {"setting": "arrivals_per_day", "a": 48.0, "b": 60.0},
        {"setting": "staff[nurse]", "a": 2, "b": 3},
    ]


def test_sim05_advice_runs_compare_on_the_recommended_staffing() -> None:
    metrics = {"wait_mean[nurse]": est(4, 1)}
    assert metrics_of({"advice": {"result": {"metrics": metrics}}}) == metrics
    assert metrics_of(None) == {}


@pytest.fixture
def client() -> Iterator[TestClient]:
    db = Database(make_engine("sqlite://"))

    def job(status: str, nurses: int, wait: float) -> None:
        result: dict[str, Any] = {
            "simulation": {"replications": 10, "metrics": {"wait_mean[nurse]": est(wait, 1)}}
        }
        with db.sessions.begin() as s:
            s.add(JobRow(version_id=1, pathway="triage", version=3, kind="simulate", status=status,
                         scenario={"staff": {"nurse": nurses}, "arrivals_per_hour": [3.0] * 24},
                         result=result if status == "done" else None))  # fmt: skip

    job("done", 2, 25)
    job("done", 3, 6)
    job("running", 4, 0)
    yield TestClient(create_app(db, fetch_version=lambda _: {}))
    db.engine.dispose()


def test_sim05_compare_endpoint(client: TestClient) -> None:
    r = client.get("/simulations/compare", params={"a": 1, "b": 2}).json()
    assert r["same_pathway_version"] and r["distinct"] == 1
    assert r["changes"] == [{"setting": "staff[nurse]", "a": 2, "b": 3}]
    assert r["metrics"][0]["better"] == "b"
    assert client.get("/simulations/compare", params={"a": 1, "b": 3}).status_code == 409
    assert client.get("/simulations/compare", params={"a": 1, "b": 9}).status_code == 404
    assert client.get("/simulations/1").json()["id"] == 1  # the single-run route still works
