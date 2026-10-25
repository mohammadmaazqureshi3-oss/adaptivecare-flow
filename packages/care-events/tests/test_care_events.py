"""Bus semantics, fault injection, outbox and inbox."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from care_events import (
    Event,
    InMemoryBus,
    OutboxBase,
    OutboxRelay,
    OutboxRow,
    add_to_outbox,
    derived_id,
    first_time,
    topic_matches,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


@pytest.mark.parametrize(
    "pattern,key,ok",
    [
        ("PatientRegistered", "PatientRegistered", True),
        ("TaskCompleted.triage.v1", "TaskCompleted.triage.v1", True),
        ("TaskCompleted.triage.v1", "TaskCompleted.triage.v2", False),
        ("*.triage.v1", "TaskFailed.triage.v1", True),
        ("*.triage.v1", "TaskFailed.x.triage.v1", False),
        ("#.v1", "TaskFailed.triage.v1", True),
        ("#", "anything.at.all", True),
        ("Case*", "CaseStarted", False),  # '*' is a whole word, not a glob
        ("TaskRequested.worklist", "TaskRequested.PredictUrgency", False),
    ],
)
def test_topic_matching(pattern: str, key: str, ok: bool) -> None:
    assert topic_matches(pattern, key) is ok


def test_routing_keys() -> None:
    req = Event("TaskRequested", target="worklist", pathway="triage", version=3)
    assert req.routing_key == "TaskRequested.worklist"
    assert req.reply("TaskCompleted", {}).routing_key == "TaskCompleted.triage.v3"
    assert Event("PatientRegistered").routing_key == "PatientRegistered"


def test_replies_and_derived_ids_are_stable() -> None:
    req = Event("TaskRequested", target="ml", case_id="c", token_id="t0", pathway="p", version=1)
    a, b = req.reply("TaskFailed", {"x": 1}), req.reply("TaskFailed", {"x": 1})
    assert a.event_id == b.event_id and (a.case_id, a.token_id) == ("c", "t0")
    assert derived_id("c", "e", 0) == derived_id("c", "e", 0) != derived_id("c", "e", 1)
    assert Event.from_json(a.to_json()) == a


def collect(bus: InMemoryBus, queue: str, bindings: list[str]) -> list[Event]:
    got: list[Event] = []
    lock = threading.Lock()

    def handler(e: Event) -> None:
        with lock:
            got.append(e)

    bus.subscribe(queue, bindings, handler)
    return got


def test_each_queue_gets_its_own_copy() -> None:
    bus = InMemoryBus()
    engine = collect(bus, "engine.triage.v1", ["PatientRegistered", "*.triage.v1"])
    worklist = collect(bus, "worklist", ["TaskRequested.worklist"])
    bus.start()
    bus.publish(Event("PatientRegistered"))
    bus.publish(Event("TaskRequested", target="worklist"))
    bus.publish(Event("TaskCompleted", pathway="triage", version=1))
    bus.publish(Event("TaskCompleted", pathway="triage", version=2))  # another engine's reply
    bus.drain()
    assert [e.type for e in engine] == ["PatientRegistered", "TaskCompleted"]
    assert [e.type for e in worklist] == ["TaskRequested"]
    bus.stop()


def test_failing_handler_gets_the_message_again() -> None:
    bus = InMemoryBus()
    calls: list[int] = []

    def flaky(e: Event) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("database down")

    bus.subscribe("q", ["#"], flaky)
    bus.start()
    bus.publish(Event("X"))
    bus.drain()
    assert len(calls) == 3 and bus.dead_letters == []
    bus.stop()


def test_poison_message_goes_to_dead_letters() -> None:
    bus = InMemoryBus(max_redeliveries=3)

    def broken(e: Event) -> None:
        raise ValueError("cannot handle")

    bus.subscribe("q", ["#"], broken)
    bus.start()
    bus.publish(Event("X"))
    bus.drain()
    assert [q for q, _ in bus.dead_letters] == ["q"]
    bus.stop()


def test_fault_injection_delivers_twice() -> None:
    bus = InMemoryBus(deliver_twice=True)
    got = collect(bus, "q", ["#"])
    bus.start()
    bus.publish(Event("X"))
    bus.drain()
    assert len(got) == 2 and got[0] == got[1]
    bus.stop()


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    OutboxBase.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_outbox_publishes_only_committed_events_once(sessions: sessionmaker[Session]) -> None:
    bus = InMemoryBus()
    got = collect(bus, "q", ["#"])
    bus.start()
    relay = OutboxRelay(sessions, bus)
    with sessions() as s:
        add_to_outbox(s, Event("Kept"))
        s.commit()
    with sessions() as s:
        add_to_outbox(s, Event("RolledBack"))
        s.rollback()
    assert relay.flush() == 1 and relay.flush() == 0
    bus.drain()
    assert [e.type for e in got] == ["Kept"]
    with sessions() as s:
        assert s.scalars(select(OutboxRow)).one().published_at is not None
    bus.stop()


def test_crash_between_publish_and_mark_gives_a_duplicate_not_a_loss(sessions: sessionmaker[Session]) -> None:
    bus = InMemoryBus()
    got = collect(bus, "q", ["#"])
    bus.start()
    relay = OutboxRelay(sessions, bus)
    with sessions() as s:
        add_to_outbox(s, Event("TaskRequested", target="q"))
        s.commit()

    def crash(_: Event) -> None:
        raise RuntimeError("relay killed after publishing")

    relay.before_mark = crash
    with pytest.raises(RuntimeError):
        relay.flush()
    relay.before_mark = None
    assert relay.flush() == 1  # restart: the unmarked row goes again
    bus.drain()
    assert len(got) == 2 and got[0].event_id == got[1].event_id  # consumers drop the copy by id
    bus.stop()


def test_inbox_filters_duplicates(sessions: sessionmaker[Session]) -> None:
    with sessions() as s:
        assert first_time(s, "e1") is True
        s.commit()
    with sessions() as s:
        assert first_time(s, "e1") is False
        assert first_time(s, "e2") is True
