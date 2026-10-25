"""ML-01 (training pipeline, metrics) and ML-02 (prediction service), NFR-PERF-04."""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import pytest
from care_events import Event, InMemoryBus
from ml.features import FEATURES, features, mental_level
from ml.main import Predictor, load_model, outputs_for
from ml.model import UrgencyModel
from training.data import load_ktas, synthetic
from training.train import decide, train, tune_threshold, urgent_recall

SEVERE = {
    "age": 71,
    "sex": "male",
    "arrival_mode": "ambulance",
    "chief_complaint": "chest pain, sweating",
    "spo2": 87,
    "sbp": 92,
    "hr": 118,
    "rr": 26,
    "temp": 37.1,
    "pain": 8,
    "mental": "alert",
}
MINOR = {
    "age": 30,
    "sex": "female",
    "arrival_mode": "walk_in",
    "chief_complaint": "insect bite",
    "spo2": 99,
    "sbp": 122,
    "hr": 72,
    "rr": 14,
    "temp": 36.7,
    "pain": 1,
    "mental": "alert",
}


@pytest.fixture(scope="module")
def model(tmp_path_factory: pytest.TempPathFactory) -> UrgencyModel:
    """A small model trained by the real pipeline (fast: 1,500 synthetic records)."""
    import joblib

    rows, labels = synthetic(1500, seed=3)
    path = tmp_path_factory.mktemp("model") / "m.joblib"
    joblib.dump(train(rows, labels, "synthetic test", "urgency-test"), path)
    return UrgencyModel.load(path)


# ---- features ----------------------------------------------------------------------------


def test_features_from_pathway_inputs() -> None:
    f = dict(zip(FEATURES, features(SEVERE), strict=True))
    assert f["male"] == 1 and f["arrival_ambulance"] == 1 and f["kw_chest"] == 1 and f["kw_trauma"] == 0
    assert f["spo2"] == 87 and f["mental"] == 1
    empty = features({})
    assert math.isnan(empty[FEATURES.index("spo2")]) and math.isnan(empty[FEATURES.index("male")])


@pytest.mark.parametrize(
    "value,level",
    [("alert", 1), ("Voice", 2), ("pain", 3), ("unresponsive", 4), (2, 2), (7, None), ("", None)],
)
def test_avpu(value: object, level: int | None) -> None:
    out = mental_level(value)
    assert math.isnan(out) if level is None else out == level


# ---- data ------------------------------------------------------------------------------------


def test_ktas_loader_reads_the_study_format_and_cleans_impossible_values(tmp_path: Path) -> None:
    csv = tmp_path / "data.csv"
    csv.write_text(
        "Group;Sex;Age;Arrival mode;Injury;Chief_complain;Mental;Pain;NRS_pain;"
        "SBP;DBP;HR;RR;BT;Saturation;KTAS_expert\n"
        "1;2;71;2;1;chest pain;1;1;8;92;60;118;26;37,1;87;2\n"
        "1;1;30;1;2;ankle sprain;1;1;3;999;80;72;14;36,7;;4\n"
        "1;1;40;1;1;bad row;1;0;0;120;80;70;14;36,5;98;??\n"
    )
    rows, labels = load_ktas(csv)
    assert labels == [2, 4]  # the row without a valid expert level is dropped
    assert rows[0]["sex"] == "male" and rows[0]["arrival_mode"] == "ambulance" and rows[0]["temp"] == 37.1
    assert math.isnan(rows[1]["sbp"]) and math.isnan(rows[1]["spo2"])  # 999 is impossible; empty is missing


def test_synthetic_data_is_reproducible_and_urgent_levels_are_rare() -> None:
    rows, labels = synthetic(3000, seed=1)
    assert synthetic(3000, seed=1) == (rows, labels)
    share = {lvl: labels.count(lvl) / len(labels) for lvl in range(1, 6)}
    assert share[1] + share[2] < 0.25 and share[3] > 0.3


# ---- ML-01: training ------------------------------------------------------------------------


def test_ml01_pipeline_compares_three_models_and_records_the_metrics(model: UrgencyModel) -> None:
    m = model.metrics
    assert {e["name"] for e in m["cross_validation"]} == {
        "logistic_regression",
        "random_forest",
        "gradient_boosting",
    }
    assert m["selected"] in {e["name"] for e in m["cross_validation"]}
    t = m["test"]
    for key in (
        "urgent_recall",
        "macro_f1",
        "under_triage",
        "over_triage",
        "brier",
        "confusion_matrix",
        "calibration",
    ):
        assert key in t
    assert len(t["confusion_matrix"]) == 5 and t["urgent_recall"] >= 0.8


def test_ml01_threshold_raises_urgent_recall_over_plain_argmax() -> None:
    probs = np.array([[0.15, 0.10, 0.45, 0.20, 0.10], [0.02, 0.03, 0.25, 0.40, 0.30]])
    assert list(decide(probs, 0.20)) == [1, 4]  # P(1)+P(2) = 0.25 ≥ 0.20: urgent, though 3 is likeliest
    assert list(decide(probs, 0.30)) == [3, 4]
    y = np.array([1, 4])
    assert (
        tune_threshold(probs, y) >= 0.2 and urgent_recall(y, decide(probs, tune_threshold(probs, y))) == 1.0
    )


# ---- ML-02: predictions -------------------------------------------------------------------------


def test_ml02_prediction_has_level_probabilities_reasons_and_version(model: UrgencyModel) -> None:
    p = model.predict(SEVERE)
    assert p.level in (1, 2) and abs(sum(p.probabilities.values()) - 1) < 1e-3
    assert 0 < p.confidence <= 1 and p.model_version == "urgency-test"
    assert 1 <= len(p.reasons) <= 3 and p.summary().startswith("ML urgency-test: level")
    assert model.predict(MINOR).level >= 4


def test_nfr_perf_04_prediction_under_100_ms_at_p95(model: UrgencyModel) -> None:
    times = []
    for _ in range(100):
        start = time.perf_counter()
        model.predict(SEVERE)
        times.append((time.perf_counter() - start) * 1000)
    assert sorted(times)[94] < 100, f"p95 {sorted(times)[94]:.1f} ms"


def request(outputs: list[str]) -> Event:
    return Event(
        "TaskRequested",
        {"inputs": SEVERE, "outputs": [{"name": o, "type": "x"} for o in outputs]},
        case_id="c",
        token_id="t0@predict#1",
        pathway="triage",
        version=2,
        target="PredictUrgency",
    )


def test_ml02_service_answers_with_exactly_the_declared_outputs(model: UrgencyModel) -> None:
    bus = InMemoryBus()
    replies: list[Event] = []
    bus.subscribe("engine", ["*.triage.v2"], replies.append)
    bus.start()
    Predictor(bus, model).on_event(request(["urgency", "confidence", "triage_note"]))
    bus.drain()
    [r] = replies
    assert r.type == "TaskCompleted" and set(r.payload["outputs"]) == {"urgency", "confidence", "triage_note"}
    assert r.payload["model_version"] == "urgency-test" and len(r.payload["probabilities"]) == 5
    assert outputs_for(request(["urgency"]), model.predict(SEVERE)).keys() == {"urgency"}
    bus.stop()


def test_without_a_model_the_task_fails_permanently_so_the_fallback_runs(tmp_path: Path) -> None:
    bus = InMemoryBus()
    replies: list[Event] = []
    bus.subscribe("engine", ["#"], replies.append)
    bus.start()
    Predictor(bus, load_model(tmp_path / "none.joblib")).on_event(request(["urgency"]))
    bus.drain()
    assert replies[0].type == "TaskFailed" and replies[0].payload["temporary"] is False
    bus.stop()


def test_the_shipped_model_file_loads() -> None:
    m = load_model()
    assert m is not None and m.version.startswith("urgency-v1")
