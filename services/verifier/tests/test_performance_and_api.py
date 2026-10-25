"""NFR-PERF-01 and the REST endpoint."""

from __future__ import annotations

import json

from builders import PATHWAYS, pw
from fastapi.testclient import TestClient
from verifier.algorithm import verify
from verifier.main import app


def test_nfr_perf_01_thirty_nodes_four_branches_under_two_seconds() -> None:
    tasks, arrows = [], []
    for b in range(4):
        chain = [f"t{b}_{k}" for k in range(7)]
        tasks += [f"{t}:task" for t in chain]
        arrows += [f"p>{chain[0]}", f"{chain[-1]}>j"]
        arrows += [f"{x}>{y}" for x, y in zip(chain, chain[1:], strict=False)]
    p = pw(f"s:start p:and_split {' '.join(tasks)} j:and_join e:end", f"s>p {' '.join(arrows)} j>e")
    assert len(p.nodes) == 32
    r = verify(p)
    assert r.status == "SAFE"
    assert r.states_explored == 8**4 + 3  # (n+1)^k inner markings + start, split, end states
    assert r.elapsed_ms < 2000, r.elapsed_ms


client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_verify_endpoint() -> None:
    doc = json.loads((PATHWAYS / "imaging_deadlock.json").read_text())
    body = client.post("/verify", json=doc).json()
    assert body["status"] == "UNSAFE"
    assert body["errors"][0]["property"]


def test_verify_endpoint_rejects_bad_model() -> None:
    assert (
        client.post("/verify", json={"id": "x", "nodes": [{"id": "a", "type": "?"}], "edges": []}).status_code
        == 422
    )
