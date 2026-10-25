"""PAT-01: as a nurse, I register and search patients."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from patient.db import Database, make_engine
from patient.main import age, create_app

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
        "Grace Hopper",
        "Alan Turing",
        "Ada Lovelace",
    ]  # newest first
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
    from care_events import Event, OutboxRow
    from sqlalchemy import select

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
