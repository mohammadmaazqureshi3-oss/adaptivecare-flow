"""patient service: patients (PAT-01); triage records and beds follow in Sprint 6 (PAT-02).

Feature IDs: C1-02. Nurses and doctors register and search patients through the
gateway, which has already checked their role and passes their identity in
``X-User-Email``. Publishing ``PatientRegistered`` so that a case starts is ENG-01
(Sprint 3), added with the transactional outbox.
"""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from patient.db import Database, PatientRow, iso, make_engine

MAX_AGE_YEARS = 130
MRN = re.compile(r"^[Pp]0*(\d{1,9})$")


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
def register(body: PatientIn, s: SessionDep, author: Author = "unknown") -> dict[str, Any]:
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
    s.commit()
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


def create_app(db: Database | None = None) -> FastAPI:
    """Build the service; tests pass an in-memory database."""
    app = FastAPI(title="AdaptiveCare patient", version="0.2.0")
    app.state.db = db or Database(make_engine())
    app.include_router(router)
    return app
