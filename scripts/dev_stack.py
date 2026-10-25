"""Run the platform locally without Docker: every built service in ONE process.

All services share one in-memory bus (care_events.InMemoryBus) in place of RabbitMQ and
keep their data in SQLite files under .dev/. Ports match the services' Compose roles:

    gateway 8000 · auth 8001 · designer 8002 · verifier 8003 · patient 8004
    worklist 8005 · ml 8006 · engines from 8010 (one per published pathway version)

Engines: until the Sprint 4 deployer exists, a watcher here starts an engine for the
latest published version of each pathway (and keeps older ones running so their cases
finish). This is a development stand-in, not DEP-01.

Usage: ./scripts/dev.sh   (sets PYTHONPATH and runs this file)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".dev"
PORTS = {
    "gateway": 8000,
    "auth": 8001,
    "designer": 8002,
    "verifier": 8003,
    "patient": 8004,
    "worklist": 8005,
    "ml": 8006,
}
log = logging.getLogger("dev_stack")


def env_defaults() -> None:
    for line in (ROOT / ".env.example").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    os.environ.pop("AMQP_URL", None)  # the shared in-memory bus replaces RabbitMQ here
    for name, port in PORTS.items():
        os.environ[f"{name.upper()}_URL"] = f"http://localhost:{port}"


def sqlite(name: str) -> str:
    return f"sqlite:///{DEV / f'{name}.db'}"


class Stack:
    def __init__(self) -> None:
        from care_events import InMemoryBus

        self.bus = InMemoryBus()
        self.servers: list[uvicorn.Server] = []
        self.engines: dict[tuple[str, int], int] = {}

    def serve(self, name: str, app: Any, port: int) -> None:
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, name=f"http:{name}", daemon=True).start()
        self.servers.append(server)
        log.info("%-22s http://localhost:%d", name, port)

    def start_services(self) -> None:
        from auth.db import Database as AuthDB
        from auth.db import make_engine as auth_engine
        from auth.main import create_app as auth_app
        from designer.db import Database as DesignerDB
        from designer.db import make_engine as designer_engine
        from designer.main import create_app as designer_app
        from gateway.main import create_app as gateway_app
        from ml.main import create_app as ml_app
        from patient.db import Database as PatientDB
        from patient.db import make_engine as patient_engine
        from patient.main import create_app as patient_app
        from verifier.main import app as verifier_app
        from worklist.db import Database as WorklistDB
        from worklist.db import make_engine as worklist_engine
        from worklist.main import create_app as worklist_app

        self.bus.start()
        self.serve("auth", auth_app(AuthDB(auth_engine(sqlite("auth")))), PORTS["auth"])
        self.serve(
            "designer", designer_app(DesignerDB(designer_engine(sqlite("designer")))), PORTS["designer"]
        )
        self.serve("verifier", verifier_app, PORTS["verifier"])
        self.serve(
            "patient", patient_app(PatientDB(patient_engine(sqlite("patient"))), self.bus), PORTS["patient"]
        )
        self.serve(
            "worklist",
            worklist_app(WorklistDB(worklist_engine(sqlite("worklist"))), self.bus),
            PORTS["worklist"],
        )
        self.serve("ml (placeholder)", ml_app(self.bus), PORTS["ml"])
        self.serve("gateway", gateway_app(), PORTS["gateway"])

    def start_engine(self, model: dict[str, Any]) -> None:
        from engine.main import create_app as engine_app
        from engine.store import Store, make_engine
        from pathway_core import Pathway

        pathway = Pathway.from_dict(model)
        key = (pathway.id, pathway.version)
        port = 8010 + len(self.engines)
        self.engines[key] = port
        store = Store(make_engine(sqlite(f"engine_{pathway.id}_v{pathway.version}")))
        self.serve(f"engine {pathway.id} v{pathway.version}", engine_app(pathway, store, self.bus), port)

    def watch_published(self) -> None:
        """Dev stand-in for the deployer: run an engine for every newly published version."""
        designer = f"http://localhost:{PORTS['designer']}"
        while True:
            try:
                for p in httpx.get(f"{designer}/pathways", timeout=5).json():
                    for number in p["published_versions"]:
                        if (p["id"], number) in self.engines:
                            continue
                        versions = httpx.get(f"{designer}/pathways/{p['id']}/versions", timeout=5).json()
                        vid = next(v["id"] for v in versions if v["number"] == number)
                        self.start_engine(httpx.get(f"{designer}/versions/{vid}", timeout=5).json()["model"])
            except (httpx.HTTPError, StopIteration) as exc:
                log.debug("watcher: %s", exc)
            time.sleep(3)

    def stop(self) -> None:
        for s in self.servers:
            s.should_exit = True
        self.bus.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("care_events.bus").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    DEV.mkdir(exist_ok=True)
    env_defaults()
    stack = Stack()
    stack.start_services()
    threading.Thread(target=stack.watch_published, name="engine-watcher", daemon=True).start()
    log.info("Ready. Publish a pathway to get its engine. Ctrl-C stops everything.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stack.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
