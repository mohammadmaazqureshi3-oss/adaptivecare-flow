"""Where engine containers run.

``DockerRuntime`` talks to the Docker Engine API over the socket (only the deployer has
it, NFR-SEC-04). ``LocalRuntime`` runs engines inside the dev stack's process. Tests use
a fake. All three answer the same three questions: start it, is it healthy, stop it.

Status: ``DockerRuntime`` follows the Docker Engine API but has not yet run against a
daemon (Docker was unavailable in Sprint 4); the deploy logic is tested with a fake.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from deployer.psm import EngineConfig


class Runtime(Protocol):
    def start(self, cfg: EngineConfig) -> None: ...

    def healthy(self, cfg: EngineConfig) -> bool: ...

    def stop(self, cfg: EngineConfig) -> None: ...

    def url(self, cfg: EngineConfig) -> str | None: ...


class DockerRuntime:
    def __init__(self, network: str, socket: str = "/var/run/docker.sock") -> None:
        self.network = network
        self.docker = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket), base_url="http://docker", timeout=30
        )

    def start(self, cfg: EngineConfig) -> None:
        body = {
            "Image": cfg.image,
            "Env": [f"{k}={v}" for k, v in sorted(cfg.env.items())],
            "Labels": cfg.labels,
            "Hostname": cfg.name,
            "HostConfig": {"NetworkMode": self.network, "RestartPolicy": {"Name": "unless-stopped"}},
        }
        r = self.docker.post("/containers/create", params={"name": cfg.name}, json=body)
        if r.status_code not in (201, 409):  # 409: it exists already, start it again
            raise RuntimeError(f"docker create failed: {r.status_code} {r.text}")
        r = self.docker.post(f"/containers/{cfg.name}/start")
        if r.status_code not in (204, 304):  # 304: already running
            raise RuntimeError(f"docker start failed: {r.status_code} {r.text}")

    def healthy(self, cfg: EngineConfig) -> bool:
        try:
            return httpx.get(f"http://{cfg.name}:{cfg.port}{cfg.health_path}", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def stop(self, cfg: EngineConfig) -> None:
        self.docker.post(f"/containers/{cfg.name}/stop")
        self.docker.delete(f"/containers/{cfg.name}")

    def url(self, cfg: EngineConfig) -> str | None:
        return f"http://{cfg.name}:{cfg.port}"


class LocalRuntime:
    """Runs engines in this process (dev stack). ``start_engine`` returns the engine's base URL."""

    def __init__(
        self,
        start_engine: Callable[[EngineConfig], str],
        stop_engine: Callable[[EngineConfig], None] | None = None,
    ) -> None:
        self.start_engine, self.stop_engine = start_engine, stop_engine
        self.urls: dict[str, str] = {}

    def start(self, cfg: EngineConfig) -> None:
        if cfg.name not in self.urls:
            self.urls[cfg.name] = self.start_engine(cfg)

    def healthy(self, cfg: EngineConfig) -> bool:
        url = self.urls.get(cfg.name)
        if url is None:
            return False
        try:
            return httpx.get(f"{url}{cfg.health_path}", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def stop(self, cfg: EngineConfig) -> None:
        if self.urls.pop(cfg.name, None) is not None and self.stop_engine:
            self.stop_engine(cfg)

    def url(self, cfg: EngineConfig) -> str | None:
        return self.urls.get(cfg.name)
