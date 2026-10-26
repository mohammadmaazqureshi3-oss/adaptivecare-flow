"""CLN-04 / NFR-MNT-03: NEWS2 as a new task type, served by a new service."""

from __future__ import annotations

from typing import Any

import pytest
from care_events import Event, InMemoryBus
from fastapi.testclient import TestClient
from scores.main import Scorer, create_app
from scores.news2 import PULSE, RESP_RATE, SPO2_SCALE1, SYSTOLIC, TEMPERATURE, band, news2, risk

NORMAL = {"rr": 16, "spo2": 98, "sbp": 125, "hr": 72, "temp": 37.0, "mental": "alert", "oxygen": False}


@pytest.mark.parametrize(
    "bands,cases",
    [
        (RESP_RATE, [(8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3)]),
        (SPO2_SCALE1, [(91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0)]),
        (SYSTOLIC, [(90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3)]),
        (
            PULSE,
            [(40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3)],
        ),
        (
            TEMPERATURE,
            [(35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1), (39.0, 1), (39.1, 2)],
        ),
    ],
    ids=["respiration", "spo2", "systolic", "pulse", "temperature"],
)
def test_cln04_news2_band_boundaries(bands: Any, cases: list[tuple[float, int]]) -> None:
    for value, points in cases:
        assert band(value, bands) == points, value


def test_cln04_normal_observations_score_zero() -> None:
    r = news2(NORMAL)
    assert (r.score, r.risk) == (0, "low") and r.note() == "NEWS2 0 (low risk)"


def test_cln04_a_sick_patient_scores_high() -> None:
    r = news2({"rr": 28, "spo2": 86, "sbp": 95, "hr": 120, "temp": 37.2, "mental": "voice", "oxygen": True})
    assert r.points == {
        "respiration": 3, "SpO2": 3, "oxygen": 2, "systolic BP": 2, "pulse": 2, "consciousness": 3,
        "temperature": 0,
    }  # fmt: skip
    assert (r.score, r.risk) == (15, "high") and r.note().startswith("NEWS2 15 (high risk): respiration 3")


@pytest.mark.parametrize(
    "score,any_three,expected",
    [
        (0, False, "low"),
        (4, False, "low"),
        (3, True, "low-medium"),
        (5, False, "medium"),
        (6, True, "medium"),
        (7, False, "high"),
    ],  # fmt: skip
)
def test_cln04_risk_thresholds(score: int, any_three: bool, expected: str) -> None:
    assert risk(score, any_three) == expected


def test_cln04_missing_observations_are_named() -> None:
    with pytest.raises(ValueError, match="NEWS2 needs spo2, mental"):
        news2({**NORMAL, "spo2": None, "mental": ""})


def request(inputs: dict[str, Any]) -> Event:
    outputs = [{"name": "news2", "type": "int"}, {"name": "news2_risk", "type": "string"}]
    return Event(
        "TaskRequested",
        {"inputs": inputs, "outputs": outputs},
        event_id="req-1",
        case_id="c1",
        token_id="t0.1@news2#1",
        pathway="triage",
        version=3,
        target="News2Score",
    )


def replies(bus: InMemoryBus, inputs: dict[str, Any]) -> list[Event]:
    got: list[Event] = []
    bus.subscribe("engine", ["*.triage.v3"], got.append)
    Scorer(bus).on_event(request(inputs))
    bus.start()
    bus.drain()
    bus.stop()
    return got


def test_nfr_mnt03_the_service_answers_the_engines_request_with_the_declared_outputs() -> None:
    [reply] = replies(InMemoryBus(), {**NORMAL, "rr": 22, "spo2": 95})
    assert reply.type == "TaskCompleted" and reply.routing_key == "TaskCompleted.triage.v3"
    assert reply.token_id == "t0.1@news2#1"
    assert reply.payload["outputs"] == {"news2": 3, "news2_risk": "low"}  # news2_note was not declared
    assert reply.payload["points"]["respiration"] == 2


def test_cln04_missing_observations_fail_permanently_so_the_fallback_runs() -> None:
    [reply] = replies(InMemoryBus(), {**NORMAL, "hr": None})
    assert reply.type == "TaskFailed" and reply.payload == {"reason": "NEWS2 needs hr", "temporary": False}


def test_cln04_an_unreadable_number_fails_permanently() -> None:
    [reply] = replies(InMemoryBus(), {**NORMAL, "rr": "fast"})
    assert reply.type == "TaskFailed" and reply.payload["temporary"] is False


def test_cln04_an_unexpected_error_is_temporary_so_the_engine_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_: dict[str, Any]) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr("scores.main.news2", broken)
    [reply] = replies(InMemoryBus(), NORMAL)
    assert reply.type == "TaskFailed" and reply.payload == {"reason": "NEWS2 failed: bug", "temporary": True}


def test_health_lists_the_task_types() -> None:
    with TestClient(create_app(InMemoryBus())) as c:
        assert c.get("/health").json()["tasks"] == ["TaskRequested.News2Score"]
