"""Database access for the patient service: its own schema (``patient``).

Name and date of birth are stored encrypted (NFR-SEC-05, ``patient.vault``); search and
the duplicate check use keyed hashes (the blind index) in ``identity`` and ``patient_terms``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

from care_events import OutboxBase
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from patient.vault import Vault

SCHEMA = "patient"


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """ISO 8601 in UTC. SQLite returns stored times without a zone; they were written in UTC."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class PatientRow(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_enc: Mapped[str] = mapped_column(Text)  # Fernet token
    dob_enc: Mapped[str] = mapped_column(Text)  # Fernet token of the ISO date
    identity: Mapped[str] = mapped_column(String(32), index=True)  # HMAC of name + birth date
    sex: Mapped[str] = mapped_column(String(10))
    arrival_mode: Mapped[str] = mapped_column(String(20))
    chief_complaint: Mapped[str] = mapped_column(String(200), default="")
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    registered_by: Mapped[str] = mapped_column(String(254))

    @property
    def mrn(self) -> str:
        """Medical record number shown to staff, e.g. P000042."""
        return f"P{self.id:06d}"


class PatientTermRow(Base):
    """Blind index for search: one keyed hash per prefix of each name word."""

    __tablename__ = "patient_terms"

    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), primary_key=True)
    term: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)


class BedRow(Base):
    """PAT-02: a bed, reserved by a Visit case (BedService task) and occupied on admission."""

    __tablename__ = "beds"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. W1-03
    ward: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(10), default="free")  # free | reserved | occupied
    patient_id: Mapped[str] = mapped_column(String(64), default="")
    case_id: Mapped[str] = mapped_column(String(36), default="")
    wait_id: Mapped[str] = mapped_column(String(120), default="")  # the engine request that reserved it
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./patient.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    if url == "sqlite://":  # in-memory, shared by every session (tests)
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})


class Database:
    def __init__(self, engine: Engine, vault: Vault | None = None) -> None:
        self.engine = engine
        self.vault = vault or Vault.from_env()
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)
        OutboxBase.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
