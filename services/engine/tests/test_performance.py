"""NFR-PERF-02: the engine handles an event in at most 200 ms at the 95th percentile,
at 50 events per second.

Patients are registered at a steady 50 per second for 6 seconds; simulated workers answer
every task, so the engine also handles their replies (several events per case, so the
real event rate is well above 50/s). For every event the time from its creation (its
timestamp) to the end of its handling, commit included, is recorded.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from care_events import Event, InMemoryBus, OutboxRelay
from engine.service import EngineService
from engine.store import Store, make_engine
from test_reliability import settle
from workers import FakeWorkers, load

RATE_PER_S = 50
SECONDS = 6
P95_LIMIT_S = 0.2


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    st = Store(make_engine(f"sqlite:///{tmp_path / 'engine.db'}"))
    yield st
    st.engine.dispose()


def test_nfr_perf_02_engine_event_latency_p95_under_200_ms_at_50_per_second(store: Store) -> None:
    bus = InMemoryBus()
    relay = OutboxRelay(store.sessions, bus, interval_s=0.005)
    svc = EngineService(load("triage"), store, relay)
    latencies: list[float] = []

    def timed(event: Event) -> None:
        svc.on_event(event)
        latencies.append((datetime.now(UTC) - datetime.fromisoformat(event.timestamp)).total_seconds())

    bus.subscribe(svc.queue_name, svc.bindings, timed)
    FakeWorkers(bus)
    bus.start()
    relay.start()
    start = time.monotonic()
    for i in range(RATE_PER_S * SECONDS):
        time.sleep(max(0.0, start + i / RATE_PER_S - time.monotonic()))  # a steady arrival stream
        bus.publish(Event("PatientRegistered", {"patient_id": f"P{i:06d}"}, event_id=f"load-{i}"))
    settle(store, bus, timeout=60)
    relay.stop()
    bus.stop()

    latencies.sort()
    p95 = latencies[int(0.95 * len(latencies))]
    rate = len(latencies) / (time.monotonic() - start)
    p50 = latencies[len(latencies) // 2]
    print(f"NFR-PERF-02: {len(latencies)} events, {rate:.0f}/s, p50 {p50 * 1000:.0f} ms,"
          f" p95 {p95 * 1000:.0f} ms, max {latencies[-1] * 1000:.0f} ms")  # fmt: skip
    assert len(latencies) >= RATE_PER_S * SECONDS * 3  # registrations plus their replies
    assert p95 <= P95_LIMIT_S
