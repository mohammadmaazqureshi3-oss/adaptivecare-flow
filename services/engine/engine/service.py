"""``on_event`` from plan Section 7: the reliable shell around the pure ``Case``.

For each inbound event, under the case's lock (I2):
1. drop it if its id was already processed (I1);
2. load the case: from memory, or from its latest snapshot plus the events after it (I3);
3. ``case.apply(event)``;
4. store the event, the outbound events and any new timers in ONE transaction (I5), then
   acknowledge. The outbox relay publishes afterwards; the scheduler fires due timers.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from care_events import Event, OutboxRelay, add_to_outbox, derived_id
from pathway_core import Pathway
from service_metrics import case_context
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from engine.case import Case
from engine.store import CaseEventRow, CaseRow, SnapshotRow, StateRow, Store, TimerRow, now

log = logging.getLogger("engine")
SNAPSHOT_EVERY = 50


class EngineService:
    def __init__(self, pathway: Pathway, store: Store, relay: OutboxRelay | None = None) -> None:
        self.pathway = pathway
        self.store = store
        self.relay = relay
        self.cache: dict[str, Case] = {}
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()
        self.trigger = Case(pathway, "probe").trigger
        with store.sessions() as s:
            flag = s.get(StateRow, "draining")
        self.draining = flag is not None and flag.value == "1"

    @property
    def queue_name(self) -> str:
        return f"engine.{self.pathway.id}.v{self.pathway.version}"

    @property
    def bindings(self) -> list[str]:
        replies = f"*.{self.pathway.id}.v{self.pathway.version}"
        return [self.trigger, replies] if self.trigger else [replies]

    def case_id_for(self, event: Event) -> str | None:
        if self.trigger is not None and event.type == self.trigger:
            # Stable: the same registration always maps to the same case, however often delivered.
            return derived_id(self.pathway.id, self.pathway.version, event.event_id)
        return event.case_id

    def _lock(self, case_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[case_id]

    # ---- the algorithm ---------------------------------------------------------------

    def drain(self) -> None:
        """DEP-02: stop taking new cases; the ones running carry on to their end."""
        with self.store.sessions.begin() as s:
            s.merge(StateRow(key="draining", value="1"))
        self.draining = True

    def running_cases(self) -> int:
        with self.store.sessions() as s:
            q = (
                select(func.count())
                .select_from(CaseRow)
                .where(CaseRow.status.in_(("running", "compensating")))
            )
            return int(s.scalar(q) or 0)

    def _is_trigger(self, event: Event) -> bool:
        return self.trigger is not None and event.type == self.trigger

    def on_event(self, event: Event) -> None:
        if self.draining and self._is_trigger(event):
            log.info("draining: not starting a new case for %s", event.event_id)  # DEP-02
            return
        case_id = self.case_id_for(event)
        if case_id is None:
            log.warning("dropping %s without a case id", event.type)
            return
        with case_context(case_id), self._lock(case_id):
            with self.store.sessions.begin() as s:
                if s.scalar(select(CaseEventRow.seq).where(CaseEventRow.event_id == event.event_id)):
                    return  # duplicate (I1)
                case = self.cache.get(case_id) or self._load(s, case_id)
                if case.status == "new" and not self._is_trigger(event):
                    log.info("ignoring %s for unknown case %s", event.type, case_id)
                    return
                try:
                    self._commit(s, case, event, case.apply(event))
                except Exception:
                    self.cache.pop(case_id, None)  # the in-memory case may be half-changed; rebuild next time
                    raise
            self.cache[case_id] = case
        if self.relay:
            self.relay.notify()

    def _commit(self, s: Session, case: Case, event: Event, outbound: list[Event]) -> None:
        log.info(
            "%s handled: case %s, %d event(s) out",
            event.type,
            case.status,
            len(outbound),
            extra={"event_type": event.type, "event_id": event.event_id, "pathway": self.pathway.id,
                   "version": self.pathway.version, "status": case.status},
        )  # fmt: skip
        row = CaseEventRow(event_id=event.event_id, case_id=case.id, event_json=event.to_json())
        s.add(row)
        for e in outbound:
            if e.type == "TimerScheduled":  # kept here, not published: the scheduler fires it
                due = datetime.fromisoformat(e.payload["due_at"])
                s.add(TimerRow(id=e.event_id, case_id=case.id, due_at=due, event_json=e.to_json()))
            else:
                add_to_outbox(s, e)
        self._summarise(s, case, event)
        if case.events % SNAPSHOT_EVERY == 0:
            s.flush()  # assigns row.seq
            snap = s.get(SnapshotRow, case.id) or SnapshotRow(case_id=case.id)
            snap.upto_seq, snap.state_json = row.seq, json.dumps(case.snapshot())
            s.add(snap)

    def _load(self, s: Session, case_id: str) -> Case:
        """Latest snapshot plus the events after it (I3); a full replay when there is none."""
        snap = s.get(SnapshotRow, case_id)
        case = Case.from_snapshot(self.pathway, case_id, json.loads(snap.state_json)) if snap else None
        return self._replay(s, case_id, case, snap.upto_seq if snap else 0)

    def _replay(self, s: Session, case_id: str, case: Case | None = None, after: int = 0) -> Case:
        case = case or Case(self.pathway, case_id)
        rows = s.scalars(
            select(CaseEventRow)
            .where(CaseEventRow.case_id == case_id, CaseEventRow.seq > after)
            .order_by(CaseEventRow.seq)
        )
        for row in rows:
            case.apply(Event.from_json(row.event_json))
        return case

    def _summarise(self, s: Session, case: Case, event: Event) -> None:
        row = s.get(CaseRow, case.id)
        if row is None:
            row = CaseRow(
                id=case.id, patient_id=str(event.payload.get("patient_id") or ""), status=case.status
            )
            s.add(row)
        row.status, row.updated_at = case.status, now()

    # ---- reads -----------------------------------------------------------------------

    def load(self, case_id: str, full_replay: bool = False) -> Case | None:
        with self.store.sessions() as s:
            case = self._replay(s, case_id) if full_replay else self._load(s, case_id)
        return None if case.status == "new" else case

    def drop_cache(self) -> None:
        """Forget every in-memory case, as after a restart."""
        self.cache.clear()

    def case_view(self, case: Case) -> dict[str, Any]:
        return {
            **case.state(),
            "pathway": self.pathway.id,
            "version": self.pathway.version,
            "history": [vars(step) for step in case.history],
        }


class Scheduler:
    """Turns due timers into ``TimerFired`` events (plan Section 7, ENG-06/07).

    Due times live in the ``timers`` table, so they survive restarts. Each fired event has
    an id derived from its timer and goes through ``on_event``, so firing twice after a
    crash changes nothing (I1). The event's time is the due time, keeping replay exact.
    """

    def __init__(
        self,
        svc: EngineService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        interval_s: float = 1.0,
    ) -> None:
        self.svc = svc
        self.clock = clock
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> int:
        """Fire every timer that is due now; returns how many fired."""
        with self.svc.store.sessions() as s:
            due = s.scalars(
                select(TimerRow)
                .where(TimerRow.fired.is_(False), TimerRow.due_at <= self.clock())
                .order_by(TimerRow.due_at)
            ).all()
        for timer in due:
            scheduled = Event.from_json(timer.event_json)
            fired = Event(
                "TimerFired",
                scheduled.payload,
                event_id=derived_id(timer.id, "fired"),
                case_id=scheduled.case_id,
                token_id=scheduled.token_id,
                pathway=scheduled.pathway,
                version=scheduled.version,
                timestamp=scheduled.payload["due_at"],
            )
            self.svc.on_event(fired)
            with self.svc.store.sessions.begin() as s:
                row = s.get(TimerRow, timer.id)
                if row is not None:
                    row.fired = True
        return len(due)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="engine-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed; retrying")
