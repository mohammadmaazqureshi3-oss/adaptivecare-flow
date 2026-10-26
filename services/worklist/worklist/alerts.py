"""WRK-03: an email or SMS when a task escalates to me (charge nurse, manager).

An admin keeps a list of alert contacts per role. When a ``NotificationRequested``
arrives, the worklist queues one delivery per active contact of that role, in the same
transaction as the notification (so no alert is lost between the two). A sender thread
delivers them with retries and backoff; a contact that keeps failing ends as ``failed``,
which the admin sees in ``/deliveries``.

Channels come from the environment: SMTP for email (``ALERT_SMTP_*``), an HTTP SMS
gateway for text messages (``ALERT_SMS_URL``, ``ALERT_SMS_TOKEN``). Without them the
alert is written to the service log instead, which is what the development stack does.
Messages carry the task label and the record number, never a patient's name.
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol

import httpx
from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from worklist.db import Base, NotificationRow, aware, iso, now

log = logging.getLogger("worklist.alerts")
MAX_ATTEMPTS = 5
BASE_DELAY_S = 30


class AlertContactRow(Base):
    __tablename__ = "alert_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(10))  # email | sms
    address: Mapped[str] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DeliveryRow(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("notification_id", "contact_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[int] = mapped_column(Integer, index=True)
    contact_id: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(10))
    address: Mapped[str] = mapped_column(String(254))
    text: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    next_try_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def queue_deliveries(s: Session, n: NotificationRow) -> int:
    """One pending delivery per active contact of the notification's role."""
    s.flush()  # the notification needs its id
    contacts = s.scalars(
        select(AlertContactRow).where(AlertContactRow.role == n.role, AlertContactRow.active.is_(True))
    ).all()
    for c in contacts:
        s.add(
            DeliveryRow(
                notification_id=n.id,
                contact_id=c.id,
                channel=c.channel,
                address=c.address,
                text=f"AdaptiveCare: {n.message}"[:500],
            )
        )
    return len(contacts)


# ---- channels -------------------------------------------------------------------------------


class Channel(Protocol):
    def send(self, address: str, text: str) -> None: ...


class LogChannel:
    """Development: the alert goes to the log (no mail server or SMS gateway needed)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def send(self, address: str, text: str) -> None:
        log.info("[%s alert, log only] to %s: %s", self.kind, address, text)


class EmailChannel:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        user: str | None = None,
        password: str | None = None,
        smtp: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self.host, self.port, self.sender, self.user, self.password = host, port, sender, user, password
        self.smtp = smtp

    def send(self, address: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, address, "AdaptiveCare alert"
        msg.set_content(text)
        with self.smtp(self.host, self.port, timeout=10) as server:
            server.starttls()
            if self.user:
                server.login(self.user, self.password or "")
            server.send_message(msg)


class SmsChannel:
    """Posts ``{"to", "text"}`` to an HTTP SMS gateway with a bearer token."""

    def __init__(self, url: str, token: str, client: httpx.Client | None = None) -> None:
        self.url, self.token = url, token
        self.client = client or httpx.Client(timeout=10)

    def send(self, address: str, text: str) -> None:
        r = self.client.post(
            self.url, json={"to": address, "text": text}, headers={"Authorization": f"Bearer {self.token}"}
        )
        r.raise_for_status()


def channels_from_env() -> dict[str, Channel]:
    env = os.environ.get
    email: Channel = LogChannel("email")
    if host := env("ALERT_SMTP_HOST"):
        email = EmailChannel(
            host,
            int(env("ALERT_SMTP_PORT", "587")),
            env("ALERT_SMTP_FROM", "alerts@adaptivecare.test"),
            env("ALERT_SMTP_USER") or None,
            env("ALERT_SMTP_PASSWORD") or None,
        )
    sms: Channel = LogChannel("sms")
    if url := env("ALERT_SMS_URL"):
        sms = SmsChannel(url, env("ALERT_SMS_TOKEN", ""))
    return {"email": email, "sms": sms}


# ---- sender ---------------------------------------------------------------------------------


class AlertSender:
    """Sends due deliveries; a failure is retried with doubling delays, then marked failed."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        channels: dict[str, Channel],
        clock: Callable[[], datetime] = now,
        interval_s: float = 2.0,
    ) -> None:
        self.sessions, self.channels, self.clock, self.interval_s = sessions, channels, clock, interval_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def send_due(self) -> int:
        """Try every pending delivery whose time has come; returns how many were sent."""
        at = self.clock()
        with self.sessions.begin() as s:
            due = [
                d
                for d in s.scalars(select(DeliveryRow).where(DeliveryRow.status == "pending"))
                if aware(d.next_try_at) <= at
            ]
            return sum(self._try(d, at) for d in due)

    def _try(self, d: DeliveryRow, at: datetime) -> bool:
        d.attempts += 1
        try:
            self.channels[d.channel].send(d.address, d.text)
        except Exception as exc:  # any channel error: record it and retry later
            d.last_error = f"{type(exc).__name__}: {exc}"[:300]
            if d.attempts >= MAX_ATTEMPTS:
                d.status = "failed"
            else:
                d.next_try_at = at + timedelta(seconds=BASE_DELAY_S * 2 ** (d.attempts - 1))
            log.warning("alert %s to contact %s failed (attempt %s)", d.id, d.contact_id, d.attempts)
            return False
        d.status, d.sent_at, d.last_error = "sent", at, ""
        return True

    def notify(self) -> None:
        self._wake.set()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="alert-sender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.send_due()
            except Exception:  # keep the thread alive; the next round retries
                log.exception("alert sender round failed")
            self._wake.wait(self.interval_s)
            self._wake.clear()


def contact_out(c: AlertContactRow) -> dict[str, Any]:
    return {
        "id": c.id,
        "role": c.role,
        "channel": c.channel,
        "address": c.address,
        "name": c.name,
        "active": c.active,
    }


def delivery_out(d: DeliveryRow) -> dict[str, Any]:
    return {
        "id": d.id,
        "notification_id": d.notification_id,
        "channel": d.channel,
        "address": d.address,
        "text": d.text,
        "status": d.status,
        "attempts": d.attempts,
        "last_error": d.last_error,
        "sent_at": iso(d.sent_at),
    }
