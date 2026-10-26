"""The token interpreter on its own (pure): ENG-01..04 behaviour on the Triage pathway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from care_events import Event
from engine.case import Case
from pathway_core import Pathway

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"
TRIAGE = Pathway.from_dict(json.loads((PATHWAYS / "triage.json").read_text()))
T0 = "2026-10-25T10:00:00+00:00"


def registered(patient_id: str = "P000001", event_id: str = "reg-1") -> Event:
    return Event("PatientRegistered", {"patient_id": patient_id, "age": 40}, event_id=event_id, timestamp=T0)


def reply(request: Event, type: str = "TaskCompleted", n: int = 0, **outputs: Any) -> Event:
    payload = {"outputs": outputs} if type == "TaskCompleted" else {"reason": "down", "temporary": False}
    return request.reply(type, payload, position=n)


def requests(events: list[Event]) -> dict[str, Event]:
    """TaskRequested events by node id."""
    return {e.payload["node"]: e for e in events if e.type == "TaskRequested"}


def started() -> tuple[Case, dict[str, Event]]:
    case = Case(TRIAGE, "case-1")
    return case, requests(case.apply(registered()))


def test_eng01_registration_starts_the_case_and_requests_both_parallel_tasks() -> None:
    case = Case(TRIAGE, "case-1")
    out = case.apply(registered())
    assert case.status == "running" and case.data == {"patient_id": "P000001"}
    assert [e.type for e in out] == [
        "CaseStarted",
        "TaskRequested",  # predict (ML)
        "TimerScheduled",  # its answer timeout (NFR-ROB-01)
        "TimerScheduled",  # the vital signs deadline
        "TaskRequested",  # vitals (nurse)
    ]
    reqs = requests(out)
    assert reqs["predict"].routing_key == "TaskRequested.PredictUrgency"
    assert reqs["vitals"].routing_key == "TaskRequested.worklist"
    assert reqs["vitals"].payload["role"] == "nurse"
    assert reqs["vitals"].payload["outputs"] == [{"name": "spo2", "type": "int"}]
    assert reqs["vitals"].payload["deadline"]["minutes"] == 10
    assert reqs["vitals"].payload["due_at"] == "2026-10-25T10:10:00+00:00"


def test_eng02_eng03_urgent_patient_is_routed_to_confirmation_and_finishes() -> None:
    case, reqs = started()
    assert case.apply(reply(reqs["predict"], urgency=2, confidence=0.9)) == []  # join waits
    out = case.apply(reply(reqs["vitals"], spo2=97))
    confirm = requests(out)["confirm"]
    assert confirm.payload["inputs"] == {"urgency": 2}
    done = case.apply(reply(confirm, confirmed_urgency=2))
    assert case.status == "completed" and [e.type for e in done] == ["CaseCompleted"]
    assert case.tokens == {}


def test_eng03_routing_uses_the_live_data_including_the_ml_output() -> None:
    def route(urgency: int, confidence: float, spo2: int) -> str:
        case, reqs = started()
        case.apply(reply(reqs["predict"], urgency=urgency, confidence=confidence))
        return next(iter(requests(case.apply(reply(reqs["vitals"], spo2=spo2)))))

    assert route(4, 0.9, 98) == "waiting"
    assert route(4, 0.9, 89) == "confirm"  # low oxygen: urgent whatever the model says
    assert route(4, 0.6, 98) == "confirm"  # unsure model: a nurse confirms
    assert route(1, 0.95, 98) == "confirm"


def test_permanent_failure_takes_the_fallback_branch() -> None:
    case, reqs = started()
    out = case.apply(reply(reqs["predict"], "TaskFailed"))
    manual = requests(out)["manual_triage"]
    assert manual.payload["role"] == "nurse"
    case.apply(reply(manual, urgency=3, confidence=1.0))
    assert "waiting" in requests(case.apply(reply(reqs["vitals"], spo2=98)))


def test_failure_without_fallback_fails_the_case_and_cancels_tokens() -> None:
    case, reqs = started()
    out = case.apply(reply(reqs["vitals"], "TaskFailed"))
    assert case.status == "failed" and [e.type for e in out] == ["CancelRequested", "CaseFailed"]
    assert out[0].routing_key == "CancelRequested.PredictUrgency"  # only the other, still running task
    assert all(t.state == "cancelled" for t in case.tokens.values())


def test_eng04_join_fires_once_and_late_or_duplicate_replies_change_nothing() -> None:
    case, reqs = started()
    case.apply(reply(reqs["predict"], urgency=4, confidence=0.9))
    first = case.apply(reply(reqs["vitals"], spo2=98))
    assert case.joins_fired == {"join1": 1} and list(requests(first)) == ["waiting"]
    before = case.state()
    again = case.apply(reply(reqs["vitals"], n=1, spo2=50))  # a second answer for the same task
    assert again == [] and case.state() == before
    assert "duplicate or late" in case.history[-1].detail


def test_wrong_outputs_are_rejected_and_a_correct_answer_still_works() -> None:
    case, reqs = started()
    case.apply(reply(reqs["vitals"], n=0, spo2="ninety"))
    assert "rejected" in case.history[-1].detail and case.tokens["t0.1"].state == "waiting"
    case.apply(reply(reqs["vitals"], n=1, spo2=95))
    assert case.data["spo2"] == 95


def test_messages_after_the_end_are_ignored() -> None:
    case, reqs = started()
    case.apply(reply(reqs["vitals"], "TaskFailed"))
    assert case.apply(reply(reqs["predict"], urgency=1, confidence=1.0)) == []
    assert case.status == "failed" and "late message" in case.history[-1].detail


def test_missing_start_input_fails_the_case() -> None:
    case = Case(TRIAGE, "c")
    case.apply(Event("PatientRegistered", {"age": 3}, event_id="r", timestamp=T0))
    assert case.status == "failed" and "patient_id" in case.reason


def test_outbound_ids_are_deterministic() -> None:
    a, b = Case(TRIAGE, "c"), Case(TRIAGE, "c")
    assert [e.event_id for e in a.apply(registered())] == [e.event_id for e in b.apply(registered())]


def test_a_late_reply_to_an_earlier_task_is_not_taken_for_the_current_one() -> None:
    """Found by the replay test: the predict token moves on to wait at manual_triage."""
    case, reqs = started()
    failed = reply(reqs["predict"], "TaskFailed")
    case.apply(failed)
    assert case.tokens["t0.0"].node == "manual_triage"
    late = reqs["predict"].reply("TaskFailed", {"reason": "retry also failed"}, position=1)  # new id
    assert case.apply(late) == [] and case.status == "running"
    assert "duplicate or late" in case.history[-1].detail


def test_history_lists_each_event_before_what_it_caused() -> None:
    case, reqs = started()
    case.apply(reply(reqs["vitals"], spo2=97))
    assert [(h.direction, h.type) for h in case.history][:4] == [
        ("in", "PatientRegistered"),
        ("out", "CaseStarted"),
        ("out", "TaskRequested"),
        ("out", "TimerScheduled"),
    ]
    assert case.history[-1].direction == "in" and "vitals completed" in case.history[-1].detail
