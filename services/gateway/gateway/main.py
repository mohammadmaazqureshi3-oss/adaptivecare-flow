"""gateway service: the single entry point for users (REST).

Feature IDs: C4-03. Checks the access token and the role on every route
(NFR-SEC-01/02, AUTH-03), then forwards the request to the service behind it,
adding ``X-User-Id``, ``X-User-Email`` and ``X-User-Role`` so that services
know who is acting without decoding the token again.
"""

import asyncio
import os
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from service_metrics import instrument

from gateway.permissions import PUBLIC, Rule, match

SERVICES = ["auth", "designer", "verifier", "simulator", "deployer", "worklist", "patient", "ml", "scores"]
FORWARDED_HEADERS = ("authorization", "content-type", "accept")


def service_url(name: str) -> str:
    return os.environ.get(f"{name.upper()}_URL", f"http://{name}:8000")


def error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def check_token(request: Request) -> dict[str, Any] | JSONResponse:
    """Return the access token's claims, or the 401 response to send."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return error(401, "missing token")
    try:
        claims: dict[str, Any] = jwt.decode(
            header.removeprefix("Bearer "), os.environ["JWT_SECRET"], algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return error(401, "invalid or expired token")
    if claims.get("type") != "access":
        return error(401, "invalid or expired token")
    return claims


def authorise(rule: Rule, request: Request) -> dict[str, str] | JSONResponse:
    """Headers to forward for ``rule``, or the 401/403 response to send instead."""
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARDED_HEADERS}
    if rule.roles is PUBLIC:
        return headers
    claims = check_token(request)
    if isinstance(claims, JSONResponse):
        return claims
    if claims.get("role") not in rule.roles:
        return error(403, "your role does not allow this action")
    return headers | {
        "x-user-id": claims["sub"],
        "x-user-email": claims["email"],
        "x-user-role": claims["role"],
    }


router = APIRouter()


def client_of(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.client
    return client


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@router.get("/health/all")
async def health_all(request: Request) -> dict[str, object]:
    """Ask every service for its health; used by the Sprint 0 demo and monitoring."""
    client = client_of(request)

    async def check(name: str) -> tuple[str, str]:
        try:
            r = await client.get(f"{service_url(name)}/health", timeout=2.0)
            return name, "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.HTTPError as exc:
            return name, f"down ({type(exc).__name__})"

    results = dict(await asyncio.gather(*(check(s) for s in SERVICES)))
    healthy = all(v == "ok" for v in results.values())
    return {"status": "ok" if healthy else "degraded", "services": results}


@router.get("/monitor/services")
async def monitor_services(request: Request) -> Any:
    """MON-03 (admins): every service's health and request metrics in one view."""
    claims = check_token(request)
    if isinstance(claims, JSONResponse):
        return claims
    if claims.get("role") != "admin":
        return error(403, "your role does not allow this action")
    client = client_of(request)
    token = os.environ.get("METRICS_TOKEN")
    auth = {"Authorization": f"Bearer {token}"} if token else {}

    async def one(name: str) -> dict[str, Any]:
        try:
            health = await client.get(f"{service_url(name)}/health", timeout=2.0)
            metrics = await client.get(f"{service_url(name)}/metrics.json", headers=auth, timeout=2.0)
        except httpx.HTTPError as exc:
            return {"service": name, "status": f"down ({type(exc).__name__})"}
        status = "ok" if health.status_code == 200 else f"http {health.status_code}"
        body = metrics.json() if metrics.status_code == 200 else {}
        return {**body, "service": name, "status": status, "health": health.json()}

    own = request.app.state.metrics.summary() | {"status": "ok"}
    return [own, *await asyncio.gather(*(one(s) for s in SERVICES))]


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    """Check the route against the permission matrix, then forward it to its service."""
    rule = match(request.method, "/" + path)
    if rule is None:
        return error(404, "no such route")
    request.state.metrics_route = f"{rule.service}:{rule.path}"
    headers = authorise(rule, request)
    if isinstance(headers, JSONResponse):
        return headers
    try:
        upstream = await client_of(request).request(
            request.method,
            f"{service_url(rule.service)}/{path}",
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
    except httpx.HTTPError:
        return error(502, f"{rule.service} is not reachable")
    return Response(
        upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type")
    )


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the gateway; tests pass a mock transport in place of the real services."""
    app = FastAPI(title="AdaptiveCare gateway", version="0.2.0")
    app.state.metrics = instrument(app, "gateway")
    app.state.client = httpx.AsyncClient(transport=transport, timeout=30.0)
    app.include_router(router)
    return app
