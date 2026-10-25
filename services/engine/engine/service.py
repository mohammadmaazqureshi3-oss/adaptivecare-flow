"""``on_event`` from plan Section 7: the reliable shell around the pure ``Case``.

For each inbound event, under the case's lock (I2):
1. drop it if its id was already processed (I1);
2. load the case: from memory, or by replaying its stored events (I3);
3. ``case.apply(event)``;
4. store the event and the outbound events in ONE transaction (I5), then acknowledge.
The outbox relay publishes afterwards.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

from care_events import Event, OutboxRelay, add_to_outbox, derived_id
from pathway_core import Pathway
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.case import Case
from engine.store import CaseEventRow, CaseRow, Store, now

log = logging.getLogger("engine")


class EngineService:
    def __init__(self, pathway: Pathway, store: Store, relay: OutboxRelay | None = None) -> None:
        self.pathway = pathway
        self.store = store
        self.relay = relay
        self.cache: dict[str, Case] = {}
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()
        self.trigger = Case(pathway, "probe").trigger

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

    def on_event(self, event: Event) -> None:
        case_id = self.case_id_for(event)
        if case_id is None:
            log.warning("dropping %s without a case id", event.type)
            return
        with self._lock(case_id):
            with self.store.sessions.begin() as s:
                if s.scalar(select(CaseEventRow.seq).where(CaseEventRow.event_id == event.event_id)):
                    return  # duplicate (I1)
                case = self.cache.get(case_id) or self._replay(s, case_id)
                if case.status == "new" and (self.trigger is None or event.type != self.trigger):
                    log.info("ignoring %s for unknown case %s", event.type, case_id)
                    return
                try:
                    outbound = case.apply(event)
                    s.add(CaseEventRow(event_id=event.event_id, case_id=case_id, event_json=event.to_json()))
                    add_to_outbox(s, *outbound)
                    self._summarise(s, case, event)
                except Exception:
                    self.cache.pop(case_id, None)  # the in-memory case may be half-changed; rebuild next time
                    raise
            self.cache[case_id] = case
        if self.relay:
            self.relay.notify()

    def _replay(self, s: Session, case_id: str) -> Case:
        """Rebuild a case from its stored inbound events (I3)."""
        case = Case(self.pathway, case_id)
        for row in s.scalars(
            select(CaseEventRow).where(CaseEventRow.case_id == case_id).order_by(CaseEventRow.seq)
        ):
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

    def load(self, case_id: str) -> Case | None:
        with self.store.sessions() as s:
            case = self._replay(s, case_id)
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
