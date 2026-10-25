"""patient service: patients (PAT-01) and beds (PAT-02, see ``patient.beds``).

Feature IDs: C1-02. Nurses and doctors register and search patients through the
gateway, which has already checked their role and passes their identity in
``X-User-Email``. Each registration also publishes ``PatientRegistered`` through the
outbox, in the same transaction, which starts a case on every deployed pathway whose
trigger matches (ENG-01). The event carries the record number, not the name.
"""

import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from care_events import Bus, Event, OutboxRelay, add_to_outbox
from care_events.rabbit import RabbitBus
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from patient.beds import BINDINGS, BedService, bed_out
from patient.db import BedRow, Database, PatientRow, iso, make_engine, now

MAX_AGE_YEARS = 130
MRN = re.compile(r"^[Pp]0*(\d{1,9})$")


class BedIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,19}$")
    ward: str = Field(min_length=1, max_length=40)


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date_of_birth: date
    sex: Literal["female", "male", "other", "unknown"]
    arrival_mode: Literal["walk_in", "ambulance", "referral", "other"]
    chief_complaint: str = Field(default="", max_length=200)
    confirm_duplicate: bool = False

    @field_validator("name")
    @classmethod
    def tidy_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def plausible_birth_date(cls, v: date) -> date:
        today = datetime.now(UTC).date()
        if v > today:
            raise ValueError("date of birth cannot be in the future")
        if today.year - v.year > MAX_AGE_YEARS:
            raise ValueError(f"date of birth is more than {MAX_AGE_YEARS} years ago")
        return v


def age(dob: date, today: date | None = None) -> int:
    today = today or datetime.now(UTC).date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def patient_out(p: PatientRow) -> dict[str, Any]:
    return {
        "id": p.id,
        "mrn": p.mrn,
        "name": p.name,
        "date_of_birth": p.date_of_birth.isoformat(),
        "age": age(p.date_of_birth),
        "sex": p.sex,
        "arrival_mode": p.arrival_mode,
        "chief_complaint": p.chief_complaint,
        "arrived_at": iso(p.arrived_at),
        "registered_by": p.registered_by,
    }


def registered_event(p: PatientRow) -> Event:
    """ENG-01 trigger. Minimum necessary data: no name or birth date leaves this service."""
    return Event(
        "PatientRegistered",
        {
            "patient_id": p.mrn,
            "age": age(p.date_of_birth),
            "sex": p.sex,
            "arrival_mode": p.arrival_mode,
            "chief_complaint": p.chief_complaint,
        },
    )


router = APIRouter()


def session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    yield from db.session()


SessionDep = Annotated[Session, Depends(session)]
Author = Annotated[str, Header(alias="x-user-email")]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "patient"}


@router.post("/patients", status_code=status.HTTP_201_CREATED)
def register(body: PatientIn, request: Request, s: SessionDep, author: Author = "unknown") -> dict[str, Any]:
    """PAT-01: register a patient. The same name and birth date needs an explicit confirmation."""
    key = body.name.lower()
    same = s.scalars(
        select(PatientRow).where(PatientRow.name_key == key, PatientRow.date_of_birth == body.date_of_birth)
    ).all()
    if same and not body.confirm_duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "a patient with this name and date of birth exists",
                "matches": [patient_out(p) for p in same],
            },
        )
    p = PatientRow(
        name=body.name,
        name_key=key,
        date_of_birth=body.date_of_birth,
        sex=body.sex,
        arrival_mode=body.arrival_mode,
        chief_complaint=body.chief_complaint.strip(),
        registered_by=author,
    )
    s.add(p)
    s.flush()  # assigns the id, so the event can carry the record number
    add_to_outbox(s, registered_event(p))
    s.commit()
    if relay := request.app.state.relay:
        relay.notify()
    return patient_out(p)


@router.get("/patients")
def search(
    s: SessionDep, q: str = "", limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict[str, Any]]:
    """PAT-01: search by record number (P000042) or by part of the name; newest arrivals first."""
    query = select(PatientRow).order_by(PatientRow.arrived_at.desc(), PatientRow.id.desc()).limit(limit)
    q = " ".join(q.split()).lower()
    if m := MRN.match(q):
        query = query.where(PatientRow.id == int(m.group(1)))
    elif q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(PatientRow.name_key.like(f"%{escaped}%", escape="\\"))
    return [patient_out(p) for p in s.scalars(query)]


@router.get("/patients/{patient_id}")
def read(patient_id: int, s: SessionDep) -> dict[str, Any]:
    p = s.get(PatientRow, patient_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient not found")
    return patient_out(p)


@router.get("/beds")
def beds(s: SessionDep, ward: str | None = None) -> list[dict[str, Any]]:
    """PAT-02: every bed with its status (free, reserved for a case, occupied)."""
    q = select(BedRow).order_by(BedRow.ward, BedRow.id)
    return [bed_out(b) for b in s.scalars(q.where(BedRow.ward == ward) if ward else q)]


@router.post("/beds", status_code=status.HTTP_201_CREATED)
def add_bed(body: BedIn, s: SessionDep) -> dict[str, Any]:
    if s.get(BedRow, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a bed with this id exists")
    bed = BedRow(id=body.id, ward=body.ward)
    s.add(bed)
    s.commit()
    return bed_out(bed)


@router.post("/beds/{bed_id}/release")
def release_bed(bed_id: str, s: SessionDep) -> dict[str, Any]:
    """Free a bed by hand (discharge, or a reservation no longer needed)."""
    bed = s.get(BedRow, bed_id)
    if bed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bed not found")
    bed.status, bed.case_id, bed.wait_id, bed.patient_id, bed.updated_at = "free", "", "", "", now()
    s.commit()
    return bed_out(bed)


def create_app(db: Database | None = None, bus: Bus | None = None) -> FastAPI:
    """Build the service; tests pass an in-memory database and, when they need events, a bus.

    Without a bus or ``AMQP_URL`` the events wait in the outbox until one is configured.
    """
    database = db or Database(make_engine())
    owns_bus = bus is None
    the_bus: Bus | None = bus or (RabbitBus(os.environ["AMQP_URL"]) if os.environ.get("AMQP_URL") else None)
    relay = OutboxRelay(database.sessions, the_bus) if the_bus else None
    if the_bus:
        the_bus.subscribe("patient", BINDINGS, BedService(database).on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if relay:
            relay.start()
        if owns_bus and the_bus:
            the_bus.start()
        yield
        if owns_bus and the_bus:
            the_bus.stop()
        if relay:
            relay.stop()

    app = FastAPI(title="AdaptiveCare patient", version="0.3.0", lifespan=lifespan)
    app.state.db, app.state.relay = database, relay
    app.include_router(router)
    return app
