"""Algorithm 2's invariants under faults (plan Section 7, Sprint 3 tests).

I1 each event changes a case at most once · I2 a join fires exactly once ·
I3 replaying a case's events rebuilds the same state · I4 one final state ·
I5 no requested task is lost after a crash.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from care_events import Event, InMemoryBus, OutboxRelay, OutboxRow
from engine import service as service_module
from engine.case import FINAL, Case
from engine.service import EngineService
from engine.store import CaseEventRow, CaseRow, Store, make_engine
from sqlalchemy import func, select
from workers import FakeWorkers, answer, load

TRIAGE = load("triage")
T0 = "2026-10-25T10:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    st = Store(make_engine(f"sqlite:///{tmp_path / 'engine.db'}"))
    yield st
    st.engine.dispose()


def registration(i: int) -> Event:
    return Event("PatientRegistered", {"patient_id": f"P{i:06d}"}, event_id=f"reg-{i}", timestamp=T0)


def run(store: Store, n: int, bus: InMemoryBus) -> EngineService:
    """Start n cases through the bus with simulated workers; wait until everything settles."""
    relay = OutboxRelay(store.sessions, bus, interval_s=0.01)
    svc = EngineService(TRIAGE, store, relay)
    bus.subscribe(svc.queue_name, svc.bindings, svc.on_event)
    FakeWorkers(bus)
    bus.start()
    relay.start()
    for i in range(n):
        bus.publish(registration(i))
    settle(store, bus)
    relay.stop()
    bus.stop()
    return svc


def settle(store: Store, bus: InMemoryBus, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        bus.drain(timeout)
        with store.sessions() as s:
            pending = s.scalar(
                select(func.count()).select_from(OutboxRow).where(OutboxRow.published_at.is_(None))
            )
            running = s.scalar(select(func.count()).select_from(CaseRow).where(CaseRow.status == "running"))
        if not pending and not running:
            return
        time.sleep(0.02)
    raise TimeoutError("cases did not finish")


def final_states(svc: EngineService) -> dict[str, dict]:
    with svc.store.sessions() as s:
        ids = s.scalars(select(CaseRow.id)).all()
    return {cid: svc.load(cid).state() for cid in ids}  # type: ignore[union-attr]


def test_eng05_every_message_twice_gives_the_same_histories(store: Store, tmp_path: Path) -> None:
    """Acceptance criterion of ENG-05: 100 cases, every message delivered twice."""
    faulty = run(store, 100, InMemoryBus(deliver_twice=True))
    clean_store = Store(make_engine(f"sqlite:///{tmp_path / 'clean.db'}"))
    clean = run(clean_store, 100, InMemoryBus())
    assert final_states(faulty) == final_states(clean)
    assert all(s["status"] in FINAL for s in final_states(faulty).values())  # I4
    with store.sessions() as s, clean_store.sessions() as c:
        # each accepted event stored once (I1): the faulty run stored exactly what the clean run did
        assert s.scalar(select(func.count()).select_from(CaseEventRow)) == c.scalar(
            select(func.count()).select_from(CaseEventRow)
        )
    clean_store.engine.dispose()


def test_shuffled_delivery_still_finishes_every_case_the_same_way(store: Store, tmp_path: Path) -> None:
    shuffled = run(store, 40, InMemoryBus(shuffle=True, deliver_twice=True, seed=7))
    clean_store = Store(make_engine(f"sqlite:///{tmp_path / 'clean.db'}"))
    assert final_states(shuffled) == final_states(run(clean_store, 40, InMemoryBus()))
    clean_store.engine.dispose()


def test_i2_concurrent_join_inputs_fire_the_join_exactly_once(store: Store) -> None:
    for i in range(30):
        svc = EngineService(TRIAGE, store)
        svc.on_event(registration(i))
        case_id = svc.case_id_for(registration(i))
        assert case_id is not None
        with store.sessions() as s:
            reqs = {
                e.payload["node"]: e
                for e in (Event.from_json(r.event_json) for r in s.scalars(select(OutboxRow)))
                if e.type == "TaskRequested" and e.case_id == case_id
            }
        replies = [answer(reqs["predict"]), answer(reqs["vitals"])]  # manual_triage path via fallback
        svc.on_event(replies[0])
        manual = _latest_request(store, case_id, "manual_triage")
        branch_a, branch_b = answer(manual), replies[1]
        svc.drop_cache()  # both threads must also race on rebuilding the case
        barrier = threading.Barrier(2)

        def deliver(e: Event, barrier: threading.Barrier = barrier, svc: EngineService = svc) -> None:
            barrier.wait()
            svc.on_event(e)

        threads = [threading.Thread(target=deliver, args=(e,)) for e in (branch_a, branch_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        case = svc.load(case_id)
        assert case is not None and case.joins_fired == {"join1": 1}
        after_join = [x for x in _requests(store, case_id) if x.payload["node"] in ("confirm", "waiting")]
        assert len(after_join) == 1, f"run {i}: the next task was requested {len(after_join)} times"


def _requests(store: Store, case_id: str) -> list[Event]:
    with store.sessions() as s:
        events = [Event.from_json(r.event_json) for r in s.scalars(select(OutboxRow).order_by(OutboxRow.id))]
    return [e for e in events if e.type == "TaskRequested" and e.case_id == case_id]


def _latest_request(store: Store, case_id: str, node: str) -> Event:
    return [e for e in _requests(store, case_id) if e.payload["node"] == node][-1]


def test_i5_crash_after_commit_before_publish_loses_nothing(store: Store) -> None:
    svc = EngineService(TRIAGE, store, relay=None)  # the engine "dies" before its relay runs
    svc.on_event(registration(1))
    bus = InMemoryBus()
    got: list[Event] = []
    bus.subscribe("worklist", ["TaskRequested.#"], got.append)
    bus.start()
    OutboxRelay(store.sessions, bus).flush()  # the restarted engine's relay
    bus.drain()
    assert sorted(e.payload["node"] for e in got) == ["predict", "vitals"]
    bus.stop()


def test_i5_crash_after_receive_before_commit_is_redelivered_and_processed_once(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = EngineService(TRIAGE, store)
    real = service_module.add_to_outbox
    crashes = iter([True])

    def crash_once(*args: object) -> None:
        if next(crashes, False):
            raise RuntimeError("engine killed mid-transaction")
        real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module, "add_to_outbox", crash_once)
    with pytest.raises(RuntimeError):
        svc.on_event(registration(1))
    with store.sessions() as s:
        assert s.scalar(select(func.count()).select_from(CaseEventRow)) == 0  # nothing half-saved
    svc.on_event(registration(1))  # the broker redelivers the unacknowledged message
    svc.on_event(registration(1))  # and once more, for good measure
    with store.sessions() as s:
        assert s.scalar(select(func.count()).select_from(CaseEventRow)) == 1
        assert s.scalar(select(func.count()).select_from(OutboxRow)) == 3  # CaseStarted + two tasks


def test_i3_replaying_1000_random_cases_rebuilds_the_same_state() -> None:
    """Random answers, random order and random duplicates; then rebuild from the inbox."""
    rng = random.Random(42)
    for i in range(1000):
        case, inbox, pending = Case(TRIAGE, f"c{i}"), [], []
        first = registration(i)
        pending += case.apply(first)
        inbox.append(first)
        while pending:
            request = pending.pop(rng.randrange(len(pending)))
            if request.type != "TaskRequested":
                continue
            reply = answer(request, fail_ml=rng.random() < 0.5)
            copies = [reply] * rng.choice([1, 1, 2])
            for r in copies:
                inbox.append(r)
                pending += case.apply(r)
        rebuilt = Case(TRIAGE, f"c{i}")
        outbound = [e for e in inbox for e in rebuilt.apply(e)]
        assert rebuilt.state() == case.state()
        assert case.status in FINAL  # I4
        assert len(outbound) == len({e.event_id for e in outbound})


def test_restart_rebuilds_cases_from_the_store(store: Store) -> None:
    svc = EngineService(TRIAGE, store)
    svc.on_event(registration(1))
    case_id = svc.case_id_for(registration(1))
    assert case_id is not None
    reqs = {e.payload["node"]: e for e in _requests(store, case_id)}
    svc.on_event(answer(reqs["vitals"]))
    before = svc.load(case_id).state()  # type: ignore[union-attr]
    restarted = EngineService(TRIAGE, store)  # empty cache, as after a crash
    restarted.on_event(answer(reqs["predict"]))
    case = restarted.load(case_id)
    assert case is not None and case.data["spo2"] == before["data"]["spo2"]
    assert case.state()["tokens"] != before["tokens"]  # it carried on from where it was


def test_a_start_without_trigger_is_not_started_by_registrations(store: Store) -> None:
    svc = EngineService(load("imaging_deadlock"), store)
    assert svc.trigger is None and svc.bindings == ["*.imaging_deadlock.v1"]
    svc.on_event(registration(1))
    with store.sessions() as s:
        assert s.scalar(select(func.count()).select_from(CaseEventRow)) == 0
