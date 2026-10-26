"""MON-03: every service counts and times its requests per route template."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from service_metrics import instrument


def app_with(token: str | None = None) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    metrics = instrument(app, "demo", token=token)
    metrics.gauge("demo_open_tasks", "Open tasks.", lambda: 3)

    @app.get("/tasks/{task_id}")
    def task(task_id: int) -> dict[str, int]:
        if task_id == 0:
            raise HTTPException(404)
        return {"id": task_id}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("bug")

    return app, TestClient(app, raise_server_exceptions=False)


def test_mon03_requests_are_counted_by_route_template_not_by_path() -> None:
    _, c = app_with()
    for i in (1, 2, 0):
        c.get(f"/tasks/{i}")
    c.get("/boom")
    c.get("/nowhere")
    text = c.get("/metrics").text
    assert 'http_requests_total{service="demo",method="GET",route="/tasks/{task_id}",status="200"} 2' in text
    assert 'route="/tasks/{task_id}",status="404"} 1' in text
    assert 'route="/boom",status="500"} 1' in text
    assert 'route="<unmatched>",status="404"} 1' in text
    assert "/tasks/1" not in text  # ids never become labels
    assert 'http_request_duration_seconds_count{service="demo",route="/tasks/{task_id}"} 3' in text
    assert 'le="+Inf"} 3' in text and 'demo_open_tasks{service="demo"} 3' in text
    assert "/metrics" not in text.split("process_uptime")[0]  # scrapes are not counted


def test_mon03_json_summary_for_the_admin_page() -> None:
    _, c = app_with()
    c.get("/tasks/1")
    c.get("/boom")
    s = c.get("/metrics.json").json()
    assert s["service"] == "demo" and s["requests"] == 2 and s["server_errors"] == 1
    assert s["p95_ms"] is not None and s["gauges"] == {"demo_open_tasks": 3}


def test_mon03_a_metrics_token_protects_both_endpoints() -> None:
    _, c = app_with(token="scrape-secret")
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics.json").status_code == 401
    ok = {"Authorization": "Bearer scrape-secret"}
    assert c.get("/metrics", headers=ok).status_code == 200
    assert c.get("/metrics.json", headers=ok).json()["requests"] == 0
