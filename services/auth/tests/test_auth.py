"""AUTH-01, AUTH-02 and NFR-SEC-01 at the auth service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from auth.db import Database, LoginLog, make_engine
from auth.main import create_app
from auth.security import make_token
from fastapi.testclient import TestClient

ADMIN = {"email": "admin@example.org", "password": "admin-pass-123"}


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    monkeypatch.setenv("JWT_SECRET", "test-secret-0123456789abcdef0123456789")
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN["email"])
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN["password"])
    return Database(make_engine("sqlite://"))


@pytest.fixture
def client(db: Database) -> TestClient:
    return TestClient(create_app(db))


def login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth02_login_returns_access_and_refresh_tokens(client: TestClient) -> None:
    body = login(client, **ADMIN)
    claims = jwt.decode(body["access_token"], "test-secret-0123456789abcdef0123456789", algorithms=["HS256"])
    assert claims["role"] == "admin" and claims["type"] == "access"
    assert claims["exp"] - claims["iat"] == 15 * 60
    refresh = jwt.decode(
        body["refresh_token"], "test-secret-0123456789abcdef0123456789", algorithms=["HS256"]
    )
    assert refresh["exp"] - refresh["iat"] == 8 * 3600


def test_auth02_wrong_password_is_refused_and_logged(client: TestClient, db: Database) -> None:
    r = client.post("/auth/login", json={"email": ADMIN["email"], "password": "nope-nope"})
    assert r.status_code == 401
    with db.sessions() as s:
        assert [row.success for row in s.query(LoginLog)] == [False]


def test_auth01_admin_creates_a_user_who_can_log_in(client: TestClient) -> None:
    token = login(client, **ADMIN)["access_token"]
    new = {"name": "Nadia Nurse", "email": "Nadia@Example.org", "password": "nurse-pass-1", "role": "nurse"}
    r = client.post("/users", json=new, headers=bearer(token))
    assert r.status_code == 201 and r.json()["email"] == "nadia@example.org"
    assert login(client, "nadia@example.org", "nurse-pass-1")["user"]["role"] == "nurse"
    assert client.post("/users", json=new, headers=bearer(token)).status_code == 409


@pytest.mark.parametrize("bad", [{"role": "surgeon"}, {"password": "short"}, {"email": "not-an-email"}])
def test_auth01_invalid_users_are_rejected(client: TestClient, bad: dict) -> None:
    token = login(client, **ADMIN)["access_token"]
    body = {"name": "X", "email": "x@example.org", "password": "long-enough", "role": "nurse", **bad}
    assert client.post("/users", json=body, headers=bearer(token)).status_code == 422


def test_auth03_non_admin_cannot_manage_users(client: TestClient) -> None:
    admin = login(client, **ADMIN)["access_token"]
    body = {"name": "D", "email": "d@example.org", "password": "designer-1", "role": "designer"}
    client.post("/users", json=body, headers=bearer(admin))
    designer = login(client, "d@example.org", "designer-1")["access_token"]
    assert client.get("/users", headers=bearer(designer)).status_code == 403


def test_deactivated_user_cannot_log_in_or_refresh(client: TestClient) -> None:
    admin = login(client, **ADMIN)["access_token"]
    body = {"name": "N", "email": "n@example.org", "password": "nurse-pass-1", "role": "nurse"}
    uid = client.post("/users", json=body, headers=bearer(admin)).json()["id"]
    refresh = login(client, "n@example.org", "nurse-pass-1")["refresh_token"]
    client.patch(f"/users/{uid}", json={"active": False}, headers=bearer(admin))
    assert (
        client.post("/auth/login", json={"email": "n@example.org", "password": "nurse-pass-1"}).status_code
        == 401
    )
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_admin_cannot_lock_themselves_out(client: TestClient) -> None:
    body = login(client, **ADMIN)
    uid = body["user"]["id"]
    r = client.patch(f"/users/{uid}", json={"role": "nurse"}, headers=bearer(body["access_token"]))
    assert r.status_code == 409


def test_role_change_applies_at_next_refresh(client: TestClient) -> None:
    admin = login(client, **ADMIN)["access_token"]
    body = {"name": "M", "email": "m@example.org", "password": "manager-1x", "role": "nurse"}
    uid = client.post("/users", json=body, headers=bearer(admin)).json()["id"]
    refresh = login(client, "m@example.org", "manager-1x")["refresh_token"]
    client.patch(f"/users/{uid}", json={"role": "manager"}, headers=bearer(admin))
    access = client.post("/auth/refresh", json={"refresh_token": refresh}).json()["access_token"]
    assert client.get("/auth/me", headers=bearer(access)).json()["role"] == "manager"
    assert (
        jwt.decode(access, "test-secret-0123456789abcdef0123456789", algorithms=["HS256"])["role"]
        == "manager"
    )


def test_nfr_sec01_missing_expired_forged_and_wrong_kind_tokens(client: TestClient) -> None:
    body = login(client, **ADMIN)
    assert client.get("/auth/me").status_code == 401
    old = make_token(1, ADMIN["email"], "admin", "access", now=datetime.now(UTC) - timedelta(minutes=16))
    assert client.get("/auth/me", headers=bearer(old)).status_code == 401
    forged = jwt.encode(
        {"sub": "1", "role": "admin", "type": "access"},
        "other-secret-0123456789abcdef0123456789",
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers=bearer(forged)).status_code == 401
    assert client.get("/auth/me", headers=bearer(body["refresh_token"])).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": body["access_token"]}).status_code == 401
