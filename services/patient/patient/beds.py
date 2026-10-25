"""PAT-02: beds — the BedService task worker and the REST views.

Pathways reserve beds with a ``BedService`` task (undo action ``ReleaseBed``). Handling is
idempotent: the same request always gets the same bed, and a release that finds nothing to
release still reports success, so redeliveries and retries change nothing twice.
"""

from __future__ import annotations

from typing import Any

from care_events import Event, add_to_outbox, first_time
from sqlalchemy import select
from sqlalchemy.orm import Session

from patient.db import BedRow, Database, iso, now

BINDINGS = [
    "TaskRequested.BedService",
    "CompensateRequested.BedService",
    "CancelRequested.BedService",
    "PatientAdmitted",
]


def bed_out(b: BedRow) -> dict[str, Any]:
    return {
        "id": b.id,
        "ward": b.ward,
        "status": b.status,
        "patient_id": b.patient_id,
        "case_id": b.case_id,
        "updated_at": iso(b.updated_at),
    }


class BedService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def on_event(self, event: Event) -> None:
        with self.db.sessions.begin() as s:
            if not first_time(s, event.event_id):
                return
            handler = {
                "TaskRequested": self._reserve,
                "CompensateRequested": self._release_for_undo,
                "CancelRequested": self._cancel,
                "PatientAdmitted": self._admit,
            }[event.type]
            handler(s, event)

    @staticmethod
    def _pick(s: Session, e: Event) -> BedRow | None:
        """The bed this request already holds (duplicate delivery), else the first free one
        (in the requested ward, if given)."""
        bed = s.scalars(
            select(BedRow).where(BedRow.wait_id == e.token_id, BedRow.status == "reserved")
        ).first()
        if bed is not None:
            return bed
        ward = (e.payload.get("inputs") or {}).get("ward")
        q = select(BedRow).where(BedRow.status == "free").order_by(BedRow.ward, BedRow.id)
        return s.scalars(q.where(BedRow.ward == ward) if ward else q).first()

    def _reserve(self, s: Session, e: Event) -> None:
        bed = self._pick(s, e)
        if bed is None:  # temporary: the engine retries with backoff, then falls back or undoes
            add_to_outbox(s, e.reply("TaskFailed", {"reason": "no free bed", "temporary": True}))
            return
        bed.status, bed.case_id, bed.wait_id, bed.updated_at = (
            "reserved",
            e.case_id or "",
            e.token_id or "",
            now(),
        )
        bed.patient_id = str(e.payload.get("patient_id") or "")
        declared = {o["name"] for o in e.payload.get("outputs", [])}
        outputs = {k: v for k, v in {"bed_id": bed.id, "ward": bed.ward}.items() if k in declared}
        add_to_outbox(s, e.reply("TaskCompleted", {"outputs": outputs}))

    def _free(self, s: Session, case_id: str | None) -> int:
        freed = 0
        for bed in s.scalars(select(BedRow).where(BedRow.case_id == case_id, BedRow.status == "reserved")):
            bed.status, bed.case_id, bed.wait_id, bed.patient_id, bed.updated_at = "free", "", "", "", now()
            freed += 1
        return freed

    def _release_for_undo(self, s: Session, e: Event) -> None:
        """Undo action ReleaseBed (ENG-08): free this case's reservation and confirm."""
        freed = self._free(s, e.case_id)
        add_to_outbox(s, e.reply("Compensated", {"ok": True, "released": freed}))

    def _cancel(self, s: Session, e: Event) -> None:
        self._free(s, e.case_id)

    def _admit(self, s: Session, e: Event) -> None:
        """The Visit pathway announces the admission: the reserved bed becomes occupied."""
        bed = s.get(BedRow, str(e.payload.get("bed_id") or ""))
        if bed is not None and bed.status == "reserved":
            bed.status, bed.updated_at = "occupied", now()
