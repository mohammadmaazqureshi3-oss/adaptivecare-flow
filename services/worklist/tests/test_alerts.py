"""WRK-03: as a charge nurse or manager, I get an email or SMS alert when a task escalates to me."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from care_events import Event, InMemoryBus
from fastapi.testclient import TestClient
from worklist.alerts import MAX_ATTEMPTS, AlertSender, EmailChannel, LogChannel, SmsChannel
from worklist.db import Database, make_engine
from worklist.main import create_app


class FakeChannel:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail_times = fail_times

    def send(self, address: str, text: str) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("gateway down")
        self.sent.append((address, text))


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(make_engine(f"sqlite:///{tmp_path / 'wl.db'}"))
    yield database
    database.engine.dispose()


@pytest.fixture
def email() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def client(db: Database, email: FakeChannel) -> Iterator[TestClient]:
    with TestClient(create_app(db, InMemoryBus(), channels={"email": email, "sms": FakeChannel()})) as c:
        yield c


def escalate(client: TestClient, role: str = "charge_nurse", event_id: str = "n-1") -> None:
    client.app.state.consumer.on_event(  # type: ignore[attr-defined]
        Event(
            "NotificationRequested",
            {"role": role, "message": "Overdue: 'Measure vital signs' for P000007 is now yours (level 1)"},
            event_id=event_id,
            case_id="c1",
        )
    )


def test_wrk03_an_escalation_is_emailed_to_the_roles_contacts(client: TestClient, db: Database) -> None:
    r = client.post(
        "/alert-contacts", json={"role": "charge_nurse", "channel": "email", "address": "cara@x.org"}
    )
    assert r.status_code == 201
    client.post("/alert-contacts", json={"role": "manager", "channel": "sms", "address": "+4915112345678"})
    escalate(client)
    escalate(client)  # duplicate delivery of the event: still one alert
    sender = AlertSender(db.sessions, {"email": (fake := FakeChannel()), "sms": FakeChannel()})
    assert sender.send_due() == 1
    [(address, text)] = fake.sent
    assert address == "cara@x.org" and "Measure vital signs" in text and text.startswith("AdaptiveCare:")
    [d] = client.get("/deliveries").json()
    assert d["status"] == "sent" and d["attempts"] == 1
    assert sender.send_due() == 0  # sent once only


def test_wrk03_the_service_sends_alerts_on_its_own(client: TestClient, email: FakeChannel) -> None:
    client.post("/alert-contacts", json={"role": "charge_nurse", "channel": "email", "address": "cara@x.org"})
    escalate(client)
    deadline = datetime.now(UTC) + timedelta(seconds=5)
    while not email.sent and datetime.now(UTC) < deadline:
        time.sleep(0.02)
    assert email.sent and email.sent[0][0] == "cara@x.org"


def test_wrk03_a_failing_channel_is_retried_then_marked_failed(client: TestClient, db: Database) -> None:
    client.post("/alert-contacts", json={"role": "manager", "channel": "sms", "address": "+4915112345678"})
    client.app.state.sender.stop()  # type: ignore[attr-defined]  # drive the sender by hand
    escalate(client, role="manager")
    clock = [datetime.now(UTC) + timedelta(seconds=1)]
    sms = FakeChannel(fail_times=MAX_ATTEMPTS)
    sender = AlertSender(db.sessions, {"sms": sms}, clock=lambda: clock[0])
    assert sender.send_due() == 0
    [d] = client.get("/deliveries").json()
    assert d["status"] == "pending" and d["attempts"] == 1 and "gateway down" in d["last_error"]
    assert sender.send_due() == 0 and client.get("/deliveries").json()[0]["attempts"] == 1  # waits 30 s
    for _ in range(MAX_ATTEMPTS):
        clock[0] += timedelta(hours=1)
        sender.send_due()
    assert client.get("/deliveries").json()[0]["status"] == "failed"


def test_wrk03_inactive_contacts_and_other_roles_get_nothing(client: TestClient) -> None:
    c = client.post(
        "/alert-contacts", json={"role": "charge_nurse", "channel": "email", "address": "a@x.org"}
    )
    assert client.patch(f"/alert-contacts/{c.json()['id']}", json={"active": False}).json()["active"] is False
    client.post("/alert-contacts", json={"role": "doctor", "channel": "email", "address": "d@x.org"})
    escalate(client)
    assert client.get("/deliveries").json() == []
    assert client.patch("/alert-contacts/99", json={"active": True}).status_code == 404
    assert [x["role"] for x in client.get("/alert-contacts").json()] == ["charge_nurse", "doctor"]


@pytest.mark.parametrize(
    "body",
    [
        {"role": "manager", "channel": "email", "address": "not-an-email"},
        {"role": "manager", "channel": "sms", "address": "015112345678"},  # not E.164
        {"role": "designer", "channel": "email", "address": "d@x.org"},  # designers get no alerts
        {"role": "manager", "channel": "pager", "address": "123"},
    ],
)
def test_wrk03_contact_addresses_are_checked(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/alert-contacts", json=body).status_code == 422


def test_wrk03_sms_channel_posts_to_the_gateway_with_a_token() -> None:
    seen: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    SmsChannel("https://sms.example/send", "tok", httpx.Client(transport=httpx.MockTransport(gateway))).send(
        "+4915112345678", "hello"
    )
    assert json.loads(seen[0].content) == {"to": "+4915112345678", "text": "hello"}
    assert seen[0].headers["authorization"] == "Bearer tok"


def test_wrk03_email_channel_uses_starttls_and_login() -> None:
    calls: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append(("connect", host, port))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            calls.append(("quit",))

        def starttls(self) -> None:
            calls.append(("starttls",))

        def login(self, user: str, password: str) -> None:
            calls.append(("login", user))

        def send_message(self, msg: Any) -> None:
            calls.append(("send", msg["To"], msg.get_content().strip()))

    EmailChannel("smtp.x", 587, "alerts@x.org", "user", "pw", smtp=FakeSMTP).send("m@x.org", "overdue")  # type: ignore[arg-type]
    assert calls == [
        ("connect", "smtp.x", 587), ("starttls",), ("login", "user"),
        ("send", "m@x.org", "overdue"), ("quit",),
    ]  # fmt: skip
    LogChannel("email").send("m@x.org", "overdue")  # development: only logs
