"""PAT-01: as a nurse, I register and search patients."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from care_events import Event, OutboxRow
from fastapi.testclient import TestClient
from patient.beds import BedService
from patient.db import Database, make_engine
from patient.main import age, create_app
from patient.vault import Vault
from sqlalchemy import select

AS_NURSE = {"x-user-email": "nadia@example.org"}
ADA = {"name": "Ada  Lovelace ", "date_of_birth": "1985-12-10", "sex": "female", "arrival_mode": "walk_in"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    db = Database(make_engine("sqlite://"))
    yield TestClient(create_app(db))
    db.engine.dispose()


def register(client: TestClient, **overrides: object) -> dict:
    r = client.post("/patients", json={**ADA, **overrides}, headers=AS_NURSE)
    assert r.status_code == 201, r.text
    return r.json()


def test_pat01_register_gives_a_record_number_and_tidy_name(client: TestClient) -> None:
    p = register(client, chief_complaint=" chest pain ")
    assert p["mrn"] == "P000001" and p["name"] == "Ada Lovelace"
    assert p["chief_complaint"] == "chest pain" and p["registered_by"] == "nadia@example.org"
    assert client.get(f"/patients/{p['id']}").json() == p


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "   "},
        {"name": ""},
        {"sex": "f"},
        {"arrival_mode": "helicopter"},
        {"date_of_birth": (datetime.now(UTC).date() + timedelta(days=1)).isoformat()},  # tomorrow
        {"date_of_birth": "1880-01-01"},
        {"date_of_birth": "not-a-date"},
        {"chief_complaint": "x" * 201},
    ],
)
def test_pat01_invalid_registrations_are_rejected(client: TestClient, bad: dict) -> None:
    assert client.post("/patients", json={**ADA, **bad}).status_code == 422


def test_born_today_is_accepted(client: TestClient) -> None:
    p = register(client, name="Newborn", date_of_birth=datetime.now(UTC).date().isoformat())
    assert p["age"] == 0


def test_pat01_possible_duplicate_needs_confirmation(client: TestClient) -> None:
    first = register(client)
    r = client.post("/patients", json={**ADA, "name": "ada lovelace"})
    assert r.status_code == 409
    assert r.json()["detail"]["matches"][0]["mrn"] == first["mrn"]
    second = register(client, name="ada lovelace", confirm_duplicate=True)
    assert second["mrn"] == "P000002"


def test_pat01_search_by_name_part_and_record_number(client: TestClient) -> None:
    ada = register(client)
    register(client, name="Alan Turing", date_of_birth="1912-06-23", sex="male", arrival_mode="ambulance")
    register(client, name="Grace Hopper", date_of_birth="1906-12-09")
    assert [p["name"] for p in client.get("/patients", params={"q": "LOVE"}).json()] == ["Ada Lovelace"]
    assert [p["name"] for p in client.get("/patients", params={"q": "a"}).json()] == [
        "Alan Turing",
        "Ada Lovelace",
    ]  # newest first; words that start with "a"
    assert [p["name"] for p in client.get("/patients", params={"q": "ada lo"}).json()] == ["Ada Lovelace"]
    assert client.get("/patients", params={"q": "ada turing"}).json() == []  # every word must match
    assert client.get("/patients", params={"q": "velace"}).json() == []  # starts of words only
    for mrn in ("P000001", "p1", " P000001 "):
        assert [p["id"] for p in client.get("/patients", params={"q": mrn}).json()] == [ada["id"]]
    assert client.get("/patients", params={"q": "P999999"}).json() == []


def test_search_treats_wildcards_literally(client: TestClient) -> None:
    register(client)
    assert client.get("/patients", params={"q": "%"}).json() == []
    assert client.get("/patients", params={"q": "_"}).json() == []


def test_search_limit_and_missing_patient(client: TestClient) -> None:
    for i in range(3):
        register(client, name=f"Patient {i}")
    assert len(client.get("/patients", params={"limit": 2}).json()) == 2
    assert client.get("/patients", params={"limit": 0}).status_code == 422
    assert client.get("/patients/999").status_code == 404


@pytest.mark.parametrize(
    "dob,today,expected",
    [
        (date(2000, 3, 15), date(2026, 3, 14), 25),  # day before the birthday
        (date(2000, 3, 15), date(2026, 3, 15), 26),  # on the birthday
        (date(2000, 2, 29), date(2026, 2, 28), 25),  # leap-day birthday
    ],
)
def test_age_boundaries(dob: date, today: date, expected: int) -> None:
    assert age(dob, today) == expected


def test_eng01_registration_queues_patient_registered_without_the_name(client: TestClient) -> None:
    p = register(client, chief_complaint="chest pain")
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.sessions() as s:
        [row] = s.scalars(select(OutboxRow)).all()
    event = Event.from_json(row.event_json)
    assert event.type == "PatientRegistered" and event.routing_key == "PatientRegistered"
    assert event.payload == {
        "patient_id": p["mrn"],
        "age": p["age"],
        "sex": "female",
        "arrival_mode": "walk_in",
        "chief_complaint": "chest pain",
    }
    assert "Lovelace" not in row.event_json and "1985" not in row.event_json


# ---- PAT-02: beds -------------------------------------------------------------------------


def bed_request(token: str = "t0@bed#1", case: str = "visit-1", event_id: str = "req-bed-1") -> Event:
    return Event(
        "TaskRequested",
        {
            "node": "reserve_bed",
            "inputs": {"patient_id": "P000001"},
            "patient_id": "P000001",
            "outputs": [{"name": "bed_id", "type": "string"}],
        },
        event_id=event_id,
        case_id=case,
        token_id=token,
        pathway="visit",
        version=1,
        target="BedService",
    )


def replies(client: TestClient) -> list[Event]:
    with client.app.state.db.sessions() as s:  # type: ignore[attr-defined]
        return [Event.from_json(r.event_json) for r in s.scalars(select(OutboxRow).order_by(OutboxRow.id))]


def service(client: TestClient) -> BedService:
    return BedService(client.app.state.db)  # type: ignore[attr-defined]


def test_pat02_reserve_is_idempotent_and_takes_a_free_bed(client: TestClient) -> None:
    for b in ("W1-01", "W1-02"):
        assert client.post("/beds", json={"id": b, "ward": "W1"}).status_code == 201
    assert client.post("/beds", json={"id": "W1-01", "ward": "W1"}).status_code == 409
    svc = service(client)
    svc.on_event(bed_request())
    svc.on_event(bed_request(event_id="req-bed-1-again"))  # a retried request: same bed
    done = [e for e in replies(client) if e.type == "TaskCompleted"]
    assert [e.payload["outputs"] for e in done] == [{"bed_id": "W1-01"}, {"bed_id": "W1-01"}]
    beds = {b["id"]: b for b in client.get("/beds").json()}
    assert beds["W1-01"]["status"] == "reserved" and beds["W1-01"]["patient_id"] == "P000001"
    assert beds["W1-02"]["status"] == "free"


def test_pat02_no_free_bed_is_a_temporary_failure(client: TestClient) -> None:
    service(client).on_event(bed_request())
    [reply] = replies(client)
    assert reply.type == "TaskFailed" and reply.payload["temporary"] is True


def test_pat02_release_bed_undo_and_admission(client: TestClient) -> None:
    client.post("/beds", json={"id": "W2-01", "ward": "W2"})
    svc = service(client)
    svc.on_event(bed_request())
    undo = Event(
        "CompensateRequested",
        {"action": "ReleaseBed"},
        event_id="undo-1",
        case_id="visit-1",
        token_id="undo:reserve_bed#5",
        pathway="visit",
        version=1,
        target="BedService",
    )
    svc.on_event(undo)
    assert replies(client)[-1].type == "Compensated" and replies(client)[-1].payload["ok"] is True
    assert client.get("/beds").json()[0]["status"] == "free"
    svc.on_event(bed_request(case="visit-2", token="t0@bed#2", event_id="req-bed-2"))
    svc.on_event(Event("PatientAdmitted", {"bed_id": "W2-01", "patient_id": "P000001"}, event_id="adm-1"))
    assert client.get("/beds").json()[0]["status"] == "occupied"
    assert client.post("/beds/W2-01/release").json()["status"] == "free"


# ---- NFR-SEC-05: encrypted at rest ----------------------------------------------------------


def test_nfr_sec05_name_and_birth_date_are_unreadable_in_the_database(client: TestClient) -> None:
    register(client, name="Ada Lovelace", date_of_birth="1985-12-10")
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.engine.connect() as c:  # the raw database, as an attacker with a copy would see it
        dump = " ".join(
            str(value)
            for table in ("patients", "patient_terms")
            for row in c.exec_driver_sql(f"SELECT * FROM {table}")  # noqa: S608 - fixed table names
            for value in row
        ).lower()
    for secret in ("ada", "lovelace", "1985", "12-10"):
        assert secret not in dump
    assert client.get("/patients/1").json()["name"] == "Ada Lovelace"  # readable through the service


def test_nfr_sec05_another_key_cannot_read_or_find_the_patients() -> None:
    engine = make_engine("sqlite://")
    TestClient(create_app(Database(engine, Vault("first-secret-" + "x" * 30)))).post(
        "/patients", json=ADA, headers=AS_NURSE
    )
    other = TestClient(create_app(Database(engine, Vault("other-secret-" + "y" * 30))))
    assert other.get("/patients", params={"q": "ada"}).json() == []
    with pytest.raises(ValueError, match="cannot be decrypted"):
        other.get("/patients/1")
    engine.dispose()


def test_nfr_sec05_the_service_needs_a_strong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="at least 32"):
        Vault("short")
    monkeypatch.delenv("PATIENT_DATA_SECRET")
    with pytest.raises(RuntimeError, match="PATIENT_DATA_SECRET"):
        Vault.from_env()
