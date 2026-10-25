"""NFR-SEC-01 and NFR-SEC-02 / AUTH-03 at the gateway.

Every rule is tried with every role: the allowed roles reach the service, the
others get 403. Upstream services are replaced by an echo transport.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from gateway.permissions import ANY_ROLE, PUBLIC, RULES

SECRET = "test-secret-0123456789abcdef0123456789"


def echo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "host": request.url.host,
            "path": request.url.path,
            "role": request.headers.get("x-user-role"),
            "email": request.headers.get("x-user-email"),
        },
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    return TestClient(create_app(httpx.MockTransport(echo)))


def token(role: str, kind: str = "access", age: timedelta = timedelta(0), secret: str = SECRET) -> str:
    iat = datetime.now(UTC) - age
    claims = {"sub": "7", "email": f"{role}@x.org", "role": role, "type": kind, "iat": iat}
    claims["exp"] = iat + timedelta(minutes=15)
    return jwt.encode(claims, secret, algorithm="HS256")


def call(client: TestClient, method: str, path: str, tok: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    return client.request(method, path, headers=headers, json={})


CASES = [(rule, role) for rule in RULES if rule.roles is not PUBLIC for role in sorted(ANY_ROLE)]


@pytest.mark.parametrize("rule,role", CASES, ids=[f"{r.method} {r.path} as {role}" for r, role in CASES])
def test_nfr_sec02_permission_matrix(client: TestClient, rule, role: str) -> None:
    path = rule.path.replace("{id}", "1")
    r = call(client, rule.method, path, token(role))
    if role in rule.roles:
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["host"] == rule.service and body["path"] == path
        assert body["role"] == role and body["email"] == f"{role}@x.org"
    else:
        assert r.status_code == 403, r.text


@pytest.mark.parametrize(
    "role,method,path",
    [
        ("nurse", "POST", "/pathways"),  # only designers create pathways
        ("manager", "POST", "/versions/1/publish"),  # managers read, never publish
        ("admin", "PUT", "/versions/1"),  # separation of duties: admins do not edit pathways
        ("designer", "POST", "/users"),  # only admins manage users
        ("doctor", "GET", "/pathways"),
        ("designer", "POST", "/patients"),  # only clinical staff register patients
        ("manager", "GET", "/patients"),
    ],
)
def test_auth03_matrix_spot_checks_from_section_10(
    client: TestClient, role: str, method: str, path: str
) -> None:
    assert call(client, method, path, token(role)).status_code == 403


def test_public_routes_need_no_token(client: TestClient) -> None:
    r = call(client, "POST", "/auth/login", None)
    assert r.status_code == 200 and r.json()["role"] is None


def test_nfr_sec01_missing_expired_forged_and_refresh_tokens(client: TestClient) -> None:
    assert call(client, "GET", "/auth/me", None).status_code == 401
    assert call(client, "GET", "/auth/me", token("admin", age=timedelta(minutes=16))).status_code == 401
    assert (
        call(
            client, "GET", "/auth/me", token("admin", secret="forged-secret-0123456789abcdef0123456789")
        ).status_code
        == 401
    )
    assert call(client, "GET", "/auth/me", token("admin", kind="refresh")).status_code == 401
    assert call(client, "GET", "/auth/me", "not.a.jwt").status_code == 401


def test_unknown_routes_are_denied_by_default(client: TestClient) -> None:
    assert call(client, "GET", "/secret-admin-panel", token("admin")).status_code == 404
    assert call(client, "DELETE", "/users/1", token("admin")).status_code == 404


def test_upstream_down_gives_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", SECRET)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    c = TestClient(create_app(httpx.MockTransport(down)))
    assert call(c, "GET", "/auth/me", token("nurse")).status_code == 502
    health = c.get("/health/all").json()
    assert health["status"] == "degraded" and set(health["services"].values()) == {"down (ConnectError)"}


def test_query_and_body_are_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["query"] = (
            str(request.url.query, "ascii") if isinstance(request.url.query, bytes) else request.url.query
        )
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"ok": True})

    c = TestClient(create_app(httpx.MockTransport(capture)))
    r = c.post(
        "/pathways?draft=1", json={"id": "triage"}, headers={"Authorization": f"Bearer {token('designer')}"}
    )
    assert r.status_code == 201 and seen == {"query": "draft=1", "body": {"id": "triage"}}
