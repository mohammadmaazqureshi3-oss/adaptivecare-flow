"""Sprint 4: deadlines and escalation (ENG-06), retries (ENG-07), compensation (ENG-08),
crash recovery with snapshots (ENG-09). Story IDs are in the test names."""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from care_events import Event, OutboxRow
from engine import service as service_module
from engine.case import Case, DoneStep, undo_levels
from engine.service import EngineService, Scheduler
from engine.store import Store, TimerRow, make_engine
from pathway_core import Pathway
from sqlalchemy import select
from workers import answer, load

T0 = datetime.fromisoformat("2026-10-25T10:00:00+00:00")
TRIAGE = load("triage")


def at(minutes: float = 0, seconds: float = 0) -> str:
    return (T0 + timedelta(minutes=minutes, seconds=seconds)).isoformat()


def registration(i: int = 1) -> Event:
    return Event("PatientRegistered", {"patient_id": f"P{i:06d}"}, event_id=f"reg-{i}", timestamp=at())


def reply_at(request: Event, type: str, when: str, n: int = 0, **payload: object) -> Event:
    return dataclasses.replace(request.reply(type, dict(payload), position=n), timestamp=when)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def set(self, minutes: float = 0, seconds: float = 0) -> None:
        self.now = T0 + timedelta(minutes=minutes, seconds=seconds)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    st = Store(make_engine(f"sqlite:///{tmp_path / 'engine.db'}"))
    yield st
    st.engine.dispose()


def outbox(store: Store) -> list[Event]:
    with store.sessions() as s:
        return [Event.from_json(r.event_json) for r in s.scalars(select(OutboxRow).order_by(OutboxRow.id))]


def requested(store: Store, node: str) -> list[Event]:
    return [e for e in outbox(store) if e.type == "TaskRequested" and e.payload["node"] == node]


def started(store: Store, pathway: Pathway = TRIAGE) -> tuple[EngineService, Scheduler, Clock]:
    svc, clock = EngineService(pathway, store), Clock()
    svc.on_event(registration())
    return svc, Scheduler(svc, clock), clock


def model_answers(svc: EngineService, store: Store) -> None:
    """The ML task answers at once, so only the nurse's deadline timers are left to fire."""
    predict = requested(store, "predict")[0]
    svc.on_event(reply_at(predict, "TaskCompleted", at(seconds=1), outputs={"urgency": 3, "confidence": 0.9}))


# ---- ENG-06: deadlines and escalation -------------------------------------------------


def test_eng06_overdue_task_escalates_along_the_chain_then_alerts_the_manager(store: Store) -> None:
    svc, scheduler, clock = started(store)
    model_answers(svc, store)
    vitals = requested(store, "vitals")[0]
    clock.set(minutes=9, seconds=59)
    assert scheduler.tick() == 1  # only the answered ML task's stale timeout; the deadline is not due
    assert not [e for e in outbox(store) if e.type == "TaskReassigned"]  # (boundary)
    clock.set(minutes=10)
    assert scheduler.tick() == 1
    reassigned = [e for e in outbox(store) if e.type == "TaskReassigned"]
    assert len(reassigned) == 1 and reassigned[0].payload == {
        "task_id": vitals.token_id,
        "role": "charge_nurse",
        "level": 1,
        "due_at": at(minutes=15),
    }
    notes = [e.payload for e in outbox(store) if e.type == "NotificationRequested"]
    assert notes[0]["role"] == "charge_nurse" and "escalation level 1" in notes[0]["message"]
    clock.set(minutes=15)
    assert scheduler.tick() == 1
    notes = [e.payload for e in outbox(store) if e.type == "NotificationRequested"]
    assert notes[-1]["role"] == "manager" and "every escalation level" in notes[-1]["message"]
    clock.set(minutes=60)
    assert scheduler.tick() == 0  # nothing more is scheduled
    # the escalated task can still be completed
    svc.on_event(reply_at(vitals, "TaskCompleted", at(minutes=61), outputs={"spo2": 97}))
    case = svc.load(svc.case_id_for(registration()) or "")
    assert case is not None and case.data["spo2"] == 97


def test_eng06_a_task_done_in_time_does_not_escalate(store: Store) -> None:
    svc, scheduler, clock = started(store)
    model_answers(svc, store)
    vitals = requested(store, "vitals")[0]
    svc.on_event(reply_at(vitals, "TaskCompleted", at(minutes=3), outputs={"spo2": 97}))
    clock.set(minutes=30)
    assert scheduler.tick() == 2  # the deadline timer and the ML answer timeout fire...
    assert not [
        e for e in outbox(store) if e.type in ("TaskReassigned", "NotificationRequested")
    ]  # ...and does nothing


def test_timers_fire_once_even_if_the_scheduler_crashes_before_marking(store: Store) -> None:
    svc, scheduler, clock = started(store)
    clock.set(minutes=10)
    scheduler.tick()
    with store.sessions.begin() as s:
        for row in s.scalars(select(TimerRow)):
            row.fired = False  # as if it crashed after firing but before marking
    Scheduler(svc, clock).tick()
    assert len([e for e in outbox(store) if e.type == "TaskReassigned"]) == 1  # I1


# ---- ENG-07: retries with backoff, then the fallback -------------------------------------


def test_eng07_temporary_failures_are_retried_with_backoff_then_fall_back(store: Store) -> None:
    svc, scheduler, clock = started(store)
    attempt1 = requested(store, "predict")[0]
    assert attempt1.attempt == 1
    svc.on_event(reply_at(attempt1, "TaskFailed", at(), reason="timeout", temporary=True))
    clock.set(seconds=0.9)
    assert scheduler.tick() == 0
    clock.set(seconds=1)  # base delay 1 s
    scheduler.tick()
    attempt2 = requested(store, "predict")[-1]
    assert attempt2.attempt == 2 and attempt2.token_id == attempt1.token_id
    svc.on_event(reply_at(attempt2, "TaskFailed", at(seconds=1), reason="timeout", temporary=True))
    clock.set(seconds=2.9)
    assert scheduler.tick() == 0
    clock.set(seconds=3)  # second delay doubles: 2 s
    scheduler.tick()
    attempt3 = requested(store, "predict")[-1]
    assert attempt3.attempt == 3
    svc.on_event(reply_at(attempt3, "TaskFailed", at(seconds=3), reason="timeout", temporary=True))
    assert [e.payload["node"] for e in outbox(store) if e.type == "TaskRequested"][-1] == "manual_triage"
    assert len(requested(store, "predict")) == 3  # max 2 retries = 3 attempts


def test_nfr_rob01_a_service_that_never_answers_is_retried_then_the_fallback_runs(store: Store) -> None:
    """The ML service is down: no reply at all. Each attempt waits 30 s for an answer."""
    svc, scheduler, clock = started(store)
    model_answers_never = requested(store, "predict")
    clock.set(seconds=29.9)
    scheduler.tick()
    assert len(requested(store, "predict")) == 1  # still waiting for the first answer
    clock.set(seconds=30)  # no answer: a temporary failure, retry 1 after 1 s
    scheduler.tick()
    clock.set(seconds=31)
    scheduler.tick()
    assert [e.attempt for e in requested(store, "predict")] == [1, 2]
    clock.set(seconds=61)  # attempt 2 unanswered: retry 2 after 2 s
    scheduler.tick()
    clock.set(seconds=63)
    scheduler.tick()
    clock.set(seconds=93)  # attempt 3 unanswered: no retries left, so the fallback
    scheduler.tick()
    assert [e.attempt for e in requested(store, "predict")] == [1, 2, 3]
    assert requested(store, "manual_triage"), "the nurse gets the manual triage task"
    # The service comes back and answers the old request: the case has moved on.
    late = reply_at(
        model_answers_never[0], "TaskCompleted", at(seconds=95), outputs={"urgency": 1, "confidence": 1}
    )
    svc.on_event(late)
    case = svc.load(svc.case_id_for(registration()) or "")
    assert case is not None and "urgency" not in case.data


def test_nfr_rob01_an_answer_in_time_cancels_nothing_and_changes_nothing(store: Store) -> None:
    svc, scheduler, clock = started(store)
    model_answers(svc, store)
    clock.set(seconds=30)
    scheduler.tick()  # the timeout fires but the task is done: ignored
    assert len(requested(store, "predict")) == 1 and not requested(store, "manual_triage")


def test_eng07_a_permanent_failure_skips_the_retries(store: Store) -> None:
    svc, _, _ = started(store)
    svc.on_event(
        reply_at(requested(store, "predict")[0], "TaskFailed", at(), reason="bad input", temporary=False)
    )
    assert requested(store, "manual_triage") and len(requested(store, "predict")) == 1


def test_a_late_success_from_an_earlier_attempt_is_accepted_once(store: Store) -> None:
    svc, scheduler, clock = started(store)
    attempt1 = requested(store, "predict")[0]
    svc.on_event(reply_at(attempt1, "TaskFailed", at(), n=0, reason="timeout", temporary=True))
    clock.set(seconds=1)
    scheduler.tick()
    late = reply_at(
        attempt1, "TaskCompleted", at(seconds=1.5), n=1, outputs={"urgency": 3, "confidence": 0.8}
    )
    svc.on_event(late)
    attempt2 = requested(store, "predict")[-1]
    svc.on_event(
        reply_at(attempt2, "TaskCompleted", at(seconds=2), outputs={"urgency": 1, "confidence": 0.9})
    )
    case = svc.load(svc.case_id_for(registration()) or "")
    assert case is not None and case.data["urgency"] == 3  # the first answer won; the second was ignored


# ---- ENG-08: compensation ------------------------------------------------------------------

VISIT = Pathway.from_dict(
    {
        "id": "visit",
        "version": 1,
        "variables": [{"name": "patient_id", "type": "string"}],
        "nodes": [
            {"id": "start", "type": "start", "trigger": "PatientRegistered", "inputs": ["patient_id"]},
            {"id": "bed", "type": "task", "kind": "service", "service": "BedService", "undo": "ReleaseBed"},
            {"id": "lab", "type": "task", "kind": "service", "service": "Lab", "undo": "CancelLabOrder"},
            {"id": "transfer", "type": "task", "kind": "service", "service": "Transport"},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "bed"},
            {"from": "bed", "to": "lab"},
            {"from": "lab", "to": "transfer"},
            {"from": "transfer", "to": "end"},
        ],
    }
)


def test_eng08_failure_without_fallback_undoes_finished_steps_in_reverse_order(store: Store) -> None:
    """Acceptance criterion: the lab order is cancelled before the bed is released."""
    svc, _, _ = started(store, VISIT)
    for node in ("bed", "lab"):
        svc.on_event(answer(requested(store, node)[0]))
    svc.on_event(
        reply_at(requested(store, "transfer")[0], "TaskFailed", at(1), reason="no porter", temporary=False)
    )
    undos = [e for e in outbox(store) if e.type == "CompensateRequested"]
    assert [(e.payload["node"], e.payload["action"], e.routing_key) for e in undos] == [
        ("lab", "CancelLabOrder", "CompensateRequested.Lab")
    ]
    svc.on_event(undos[0].reply("Compensated", {"ok": True}))
    undos = [e for e in outbox(store) if e.type == "CompensateRequested"]
    assert [e.payload["node"] for e in undos] == ["lab", "bed"]  # the bed only after the lab
    svc.on_event(undos[1].reply("Compensated", {"ok": True}))
    case = svc.load(svc.case_id_for(registration()) or "")
    assert case is not None and case.status == "compensated"
    assert outbox(store)[-1].type == "CaseCompensated"


def test_eng08_a_failing_undo_fails_the_case_and_alerts_the_manager(store: Store) -> None:
    svc, _, _ = started(store, VISIT)
    for node in ("bed", "lab"):
        svc.on_event(answer(requested(store, node)[0]))
    svc.on_event(reply_at(requested(store, "transfer")[0], "TaskFailed", at(1), reason="x", temporary=False))
    undo = next(e for e in outbox(store) if e.type == "CompensateRequested")
    svc.on_event(undo.reply("Compensated", {"ok": False}))
    case = svc.load(svc.case_id_for(registration()) or "")
    assert case is not None and case.status == "failed"
    assert any(e.type == "NotificationRequested" and e.payload["role"] == "manager" for e in outbox(store))


def test_independent_steps_are_undone_together_and_running_branches_cancelled() -> None:
    done = [DoneStep("a", 1, 3), DoneStep("b", 2, 4), DoneStep("c", 5, 6)]  # a and b ran in parallel, then c
    assert [[s.node for s in level] for level in undo_levels(done)] == [["c"], ["a", "b"]]
    assert undo_levels([]) == []


def test_compensating_case_ignores_ordinary_replies() -> None:
    case = Case(VISIT, "c")
    out = case.apply(registration())
    bed = next(e for e in out if e.type == "TaskRequested")
    out = case.apply(answer(bed))
    lab = next(e for e in out if e.type == "TaskRequested")
    out = case.apply(answer(lab))
    transfer = next(e for e in out if e.type == "TaskRequested")
    case.apply(transfer.reply("TaskFailed", {"reason": "x", "temporary": False}))
    assert case.status == "compensating"
    assert case.apply(answer(transfer)) == [] and case.status == "compensating"


# ---- ENG-09: crash recovery --------------------------------------------------------------------


def test_eng09_snapshot_plus_tail_equals_full_replay(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "SNAPSHOT_EVERY", 2)
    svc, scheduler, clock = started(store)
    svc.on_event(answer(requested(store, "predict")[0]))
    svc.on_event(answer(requested(store, "manual_triage")[0]))
    clock.set(minutes=10)
    scheduler.tick()
    case_id = svc.case_id_for(registration()) or ""
    with_snapshot = svc.load(case_id)
    full = svc.load(case_id, full_replay=True)
    assert with_snapshot is not None and full is not None
    assert with_snapshot.state() == full.state()
    assert [vars(h) for h in with_snapshot.history] == [vars(h) for h in full.history]


def test_eng09_fifty_cases_resume_after_a_crash_and_no_task_is_requested_twice(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion: 50 running cases, engine killed and restarted."""
    monkeypatch.setattr(service_module, "SNAPSHOT_EVERY", 3)
    svc = EngineService(TRIAGE, store)
    for i in range(50):
        svc.on_event(registration(i))
    for req in [e for e in outbox(store) if e.type == "TaskRequested" and e.payload["node"] == "predict"]:
        svc.on_event(answer(req))  # ml fails: each case now waits for manual triage and vitals
    before = {cid: c.state() for cid, c in svc.cache.items()}

    restarted = EngineService(TRIAGE, store)  # killed: the memory is gone, the store remains
    assert {cid: restarted.load(cid).state() for cid in before} == before  # type: ignore[union-attr]
    pending = [e for e in outbox(store) if e.type == "TaskRequested" and e.payload["node"] != "predict"]
    for req in pending:
        restarted.on_event(answer(req))
    for req in [
        e for e in outbox(store) if e.type == "TaskRequested" and e.payload["node"] in ("confirm", "waiting")
    ]:
        restarted.on_event(answer(req))
    assert all(restarted.load(cid).status == "completed" for cid in before)  # type: ignore[union-attr]
    counts = Counter((e.case_id, e.token_id, e.attempt) for e in outbox(store) if e.type == "TaskRequested")
    assert len(counts) == 50 * 4 and set(counts.values()) == {1}  # each task requested exactly once


# ---- DEP-02: draining ---------------------------------------------------------------------------


def test_dep02_a_draining_engine_finishes_running_cases_but_starts_no_new_ones(store: Store) -> None:
    svc, _, _ = started(store, VISIT)
    assert svc.running_cases() == 1
    svc.drain()
    svc.on_event(registration(2))  # a new patient: ignored while draining
    assert svc.running_cases() == 1
    for node in ("bed", "lab", "transfer"):
        svc.on_event(answer(requested(store, node)[0]))
    assert svc.running_cases() == 0
    assert EngineService(VISIT, store).draining  # the flag survives a restart
