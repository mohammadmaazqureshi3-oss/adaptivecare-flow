"""Database access for the designer service: its own schema (``designer``).

A pathway has numbered versions. A version is a draft until it is verified SAFE,
and immutable once published (DES-05). ``DATABASE_URL`` selects the server.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = "designer"


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """ISO 8601 in UTC. SQLite returns stored times without a zone; they were written in UTC."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class PathwayRow(Base):
    __tablename__ = "pathways"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    versions: Mapped[list[VersionRow]] = relationship(back_populates="pathway", order_by="VersionRow.number")


class VersionRow(Base):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("pathway_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pathway_id: Mapped[str] = mapped_column(ForeignKey("pathways.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | verified | published
    model: Mapped[dict[str, Any]] = mapped_column(JSON)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    author: Mapped[str] = mapped_column(String(254))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pathway: Mapped[PathwayRow] = relationship(back_populates="versions")


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./designer.db")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    if url == "sqlite://":  # in-memory, shared by every session (tests)
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False})


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(engine, expire_on_commit=False)
        Base.metadata.create_all(engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
