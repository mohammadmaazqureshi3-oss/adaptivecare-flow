"""MON-03: the same request metrics for every service, scraped by Prometheus.

``instrument(app, "worklist")`` counts requests and errors and times them per route
template (``/tasks/{task_id}/claim``, never the concrete path, so ids stay out of the
metrics), and serves them at ``/metrics`` (Prometheus text format) and ``/metrics.json``
(for the admin's service page). Services add gauges for their own state, e.g. open tasks.
If ``METRICS_TOKEN`` is set, both endpoints need it as a bearer token.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)  # seconds
UNMATCHED = "<unmatched>"


class Metrics:
    def __init__(self, service: str) -> None:
        self.service = service
        self.started = time.time()
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, int], int] = {}  # (method, route, status) -> count
        self.buckets: dict[str, list[int]] = {}  # route -> cumulative counts per bucket (+Inf last)
        self.seconds: dict[str, float] = {}
        self.gauges: dict[str, tuple[str, Callable[[], float]]] = {}

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            key = (method, route, status)
            self.requests[key] = self.requests.get(key, 0) + 1
            counts = self.buckets.setdefault(route, [0] * (len(BUCKETS) + 1))
            for i, upper in enumerate(BUCKETS):
                if seconds <= upper:
                    counts[i] += 1
            counts[-1] += 1
            self.seconds[route] = self.seconds.get(route, 0.0) + seconds

    def gauge(self, name: str, help_text: str, read: Callable[[], float]) -> None:
        """A value read at scrape time, e.g. the number of open tasks."""
        self.gauges[name] = (help_text, read)

    def render(self) -> str:
        """Prometheus text exposition format 0.0.4."""
        svc = f'service="{self.service}"'
        lines = [
            "# HELP http_requests_total Requests handled, by route template and status.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status), n in sorted(self.requests.items()):
                labels = f'{svc},method="{method}",route="{route}",status="{status}"'
                lines.append(f"http_requests_total{{{labels}}} {n}")
            lines += [
                "# HELP http_request_duration_seconds Time to answer a request.",
                "# TYPE http_request_duration_seconds histogram",
            ]
            for route, counts in sorted(self.buckets.items()):
                for upper, n in zip([*map(str, BUCKETS), "+Inf"], counts, strict=True):
                    lines.append(
                        f'http_request_duration_seconds_bucket{{{svc},route="{route}",le="{upper}"}} {n}'
                    )
                lines.append(
                    f'http_request_duration_seconds_sum{{{svc},route="{route}"}} {self.seconds[route]:.6f}'
                )
                lines.append(f'http_request_duration_seconds_count{{{svc},route="{route}"}} {counts[-1]}')
        lines += [
            "# TYPE process_uptime_seconds gauge",
            f"process_uptime_seconds{{{svc}}} {self.uptime():.0f}",
        ]
        for name, (help_text, read) in sorted(self.gauges.items()):
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name}{{{svc}}} {read():g}"]
        return "\n".join(lines) + "\n"

    def uptime(self) -> float:
        return time.time() - self.started

    def summary(self) -> dict[str, Any]:
        """Totals for the admin page: requests, server errors, p95 latency (bucket upper bound)."""
        with self._lock:
            total = sum(self.requests.values())
            errors = sum(n for (_, _, status), n in self.requests.items() if status >= 500)
            merged = [sum(c[i] for c in self.buckets.values()) for i in range(len(BUCKETS) + 1)]
        return {
            "service": self.service,
            "uptime_s": round(self.uptime()),
            "requests": total,
            "server_errors": errors,
            "p95_ms": _p95_ms(merged, total),
            "gauges": {name: read() for name, (_, read) in sorted(self.gauges.items())},
        }


def _p95_ms(cumulative: list[int], total: int) -> float | None:
    """Upper bound of the first bucket holding 95% of requests; None if none or beyond 5 s."""
    bound = next((b for b, n in zip(BUCKETS, cumulative, strict=False) if total and n >= 0.95 * total), None)
    return None if bound is None else bound * 1000


def _allowed(request: Request, token: str | None) -> bool:
    if not token:
        return True
    given = request.headers.get("authorization", "").removeprefix("Bearer ")
    return hmac.compare_digest(given.encode(), token.encode())


def instrument(app: Starlette, service: str, token: str | None = None) -> Metrics:
    """Add the middleware and the two endpoints. Call before adding catch-all routes."""
    metrics = Metrics(service)
    token = token if token is not None else os.environ.get("METRICS_TOKEN") or None

    async def measure(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # The gateway names a proxied request by its permission rule (one catch-all route).
            route = str(
                getattr(request.state, "metrics_route", None)
                or getattr(request.scope.get("route"), "path", UNMATCHED)
            )
            if request.url.path not in ("/metrics", "/metrics.json"):
                metrics.observe(request.method, route, status, time.perf_counter() - start)

    async def prometheus(request: Request) -> Response:
        if not _allowed(request, token):
            return PlainTextResponse("metrics token required", status_code=401)
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    async def as_json(request: Request) -> Response:
        if not _allowed(request, token):
            return JSONResponse({"detail": "metrics token required"}, status_code=401)
        return JSONResponse(metrics.summary())

    app.add_middleware(BaseHTTPMiddleware, dispatch=measure)
    app.add_route("/metrics", prometheus, methods=["GET"])
    app.add_route("/metrics.json", as_json, methods=["GET"])
    return metrics
