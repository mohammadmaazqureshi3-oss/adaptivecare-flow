"""DES-01/02/03/05 and VER-01's publish rule at the designer service.

The real Verifier (Algorithm 1) is called in-process in place of the HTTP client,
so these tests also check that the designer and verifier agree on the model.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from designer.db import Database, make_engine
from designer.main import create_app
from fastapi.testclient import TestClient
from pathway_core import Pathway
from verifier.algorithm import verify

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"
AS_DESIGNER = {"x-user-email": "dana@example.org"}


def in_process_verifier(model: dict[str, Any]) -> dict[str, Any]:
    return verify(Pathway.from_dict(model)).to_dict()


@pytest.fixture
def client() -> Iterator[TestClient]:
    db = Database(make_engine("sqlite://"))
    yield TestClient(create_app(db, verify=in_process_verifier))
    db.engine.dispose()


def load(name: str) -> dict[str, Any]:
    return json.loads((PATHWAYS / f"{name}.json").read_text())


def new_pathway(client: TestClient, pid: str = "triage") -> dict[str, Any]:
    r = client.post("/pathways", json={"id": pid, "name": "Triage"}, headers=AS_DESIGNER)
    assert r.status_code == 201, r.text
    return r.json()


def test_des01_new_pathway_starts_as_a_valid_draft(client: TestClient) -> None:
    p = new_pathway(client)
    assert p["latest_version"]["number"] == 1 and p["latest_version"]["status"] == "draft"
    assert p["created_by"] == "dana@example.org"
    assert client.post("/pathways", json={"id": "triage", "name": "x"}).status_code == 409
    assert client.post("/pathways", json={"id": "Bad Id", "name": "x"}).status_code == 422


def test_des01_des02_save_a_drawn_pathway_with_variables(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    r = client.put(f"/versions/{vid}", json={"model": load("triage")}, headers=AS_DESIGNER)
    assert r.status_code == 200, r.text
    saved = client.get(f"/versions/{vid}").json()["model"]
    assert saved["id"] == "triage" and saved["version"] == 1
    assert {v["name"] for v in saved["variables"]} >= {"urgency", "spo2", "confidence"}
    assert next(n for n in saved["nodes"] if n["id"] == "vitals")["deadline"]["minutes"] == 10


def test_invalid_model_is_rejected(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    bad = {"nodes": [{"id": "a", "type": "teleport"}], "edges": []}
    assert client.put(f"/versions/{vid}", json={"model": bad}).status_code == 422


def test_ver01_publish_is_blocked_until_verified_safe(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    client.put(f"/versions/{vid}", json={"model": load("imaging_deadlock")})
    assert client.post(f"/versions/{vid}/publish").status_code == 409  # never verified
    v = client.post(f"/versions/{vid}/verify").json()
    assert v["status"] == "draft" and v["report"]["status"] == "UNSAFE"
    assert any(e["type"] == "deadlock" for e in v["report"]["errors"])
    assert client.post(f"/versions/{vid}/publish").status_code == 409  # unsafe

    client.put(f"/versions/{vid}", json={"model": load("imaging_fixed")})
    assert client.post(f"/versions/{vid}/verify").json()["status"] == "verified"
    published = client.post(f"/versions/{vid}/publish").json()
    assert published["status"] == "published" and published["published_at"]


def test_editing_after_verify_requires_verifying_again(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    client.post(f"/versions/{vid}/verify")
    model = client.get(f"/versions/{vid}").json()["model"]
    v = client.put(f"/versions/{vid}", json={"model": model}).json()
    assert v["status"] == "draft" and v["report"] is None
    assert client.post(f"/versions/{vid}/publish").status_code == 409


def test_des05_published_versions_are_immutable_and_new_drafts_copy_them(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    client.put(f"/versions/{vid}", json={"model": load("triage")})
    client.post(f"/versions/{vid}/verify")
    client.post(f"/versions/{vid}/publish")

    assert client.put(f"/versions/{vid}", json={"model": load("triage")}).status_code == 409
    assert client.post(f"/versions/{vid}/publish").status_code == 409

    draft = client.post("/pathways/triage/versions", headers=AS_DESIGNER).json()
    assert draft["number"] == 2 and draft["status"] == "draft"
    assert draft["model"]["version"] == 2 and len(draft["model"]["nodes"]) == len(load("triage")["nodes"])
    # only one open draft at a time
    assert client.post("/pathways/triage/versions").status_code == 409
    versions = client.get("/pathways/triage/versions").json()
    assert [(v["number"], v["status"]) for v in versions] == [(1, "published"), (2, "draft")]
    assert client.get("/pathways/triage").json()["published_versions"] == [1]


def test_rename_and_list(client: TestClient) -> None:
    new_pathway(client, "visit")
    client.patch("/pathways/visit", json={"name": "Ward visit"})
    assert [p["name"] for p in client.get("/pathways").json()] == ["Ward visit"]
    assert client.get("/pathways/nope").status_code == 404
    assert client.get("/versions/999").status_code == 404


@pytest.mark.parametrize(
    "condition,ok,kind",
    [
        ("urgency <= 2 or spo2 < 90", True, None),
        ("urgency <=", False, "syntax"),
        ("urgency < 'high'", False, "type"),
        ("pulse > 100", False, "type"),
    ],
)
def test_des03_condition_check_while_typing(
    client: TestClient, condition: str, ok: bool, kind: str | None
) -> None:
    variables = [{"name": "urgency", "type": "int"}, {"name": "spo2", "type": "int"}]
    body = client.post("/conditions/check", json={"condition": condition, "variables": variables}).json()
    assert body["ok"] is ok
    if kind:
        assert body["errors"][0]["kind"] == kind and "pos" in body["errors"][0]


def test_des04_task_policies_are_saved_and_checked_before_publish(client: TestClient) -> None:
    vid = new_pathway(client)["latest_version"]["id"]
    model = load("triage")
    vitals = next(n for n in model["nodes"] if n["id"] == "vitals")
    vitals["deadline"] = {"minutes": 10, "escalation": [{"role": "charge_nurse", "afterMin": 5}]}
    vitals["undo"] = "CancelVitals"
    client.put(f"/versions/{vid}", json={"model": model})
    saved = next(n for n in client.get(f"/versions/{vid}").json()["model"]["nodes"] if n["id"] == "vitals")
    assert saved["undo"] == "CancelVitals" and saved["deadline"]["escalation"][0]["role"] == "charge_nurse"
    assert client.post(f"/versions/{vid}/verify").json()["status"] == "verified"

    vitals["deadline"]["escalation"][0]["afterMin"] = 0  # a draft may be saved half-finished...
    assert client.put(f"/versions/{vid}", json={"model": model}).status_code == 200
    v = client.post(f"/versions/{vid}/verify").json()  # ...but not published
    assert v["status"] == "draft" and [e["type"] for e in v["report"]["errors"]] == ["settings"]
    assert client.post(f"/versions/{vid}/publish").status_code == 409
