"""Run the platform locally without Docker: every built service in ONE process.

All services share one in-memory bus (care_events.InMemoryBus) in place of RabbitMQ and
keep their data in SQLite files under .dev/. Ports match the services' Compose roles:

    gateway 8000 · auth 8001 · designer 8002 · verifier 8003 · patient 8004
    worklist 8005 · ml 8006 · deployer 8007 · engines from 8010 (one per deployed version)

Engines: the deployer (DEP-01) runs here with a local runtime, so pressing Deploy as an
admin starts that version's engine inside this process instead of a Docker container.

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
    "deployer": 8007,
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
        from deployer.db import Database as DeployerDB
        from deployer.db import make_engine as deployer_engine
        from deployer.main import create_app as deployer_app
        from deployer.runtime import LocalRuntime
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
        designer_db = DesignerDB(designer_engine(sqlite("designer")))
        self.serve("designer", designer_app(designer_db, bus=self.bus), PORTS["designer"])
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
        runtime = LocalRuntime(self.start_engine)
        deployer = deployer_app(DeployerDB(deployer_engine(sqlite("deployer"))), self.bus, runtime)
        self.serve("deployer", deployer, PORTS["deployer"])

    def start_engine(self, cfg: Any) -> str:
        """LocalRuntime callback: run the engine for a deployment config in this process."""
        from engine.main import create_app as engine_app
        from engine.store import Store, make_engine
        from pathway_core import Pathway

        designer = f"http://localhost:{PORTS['designer']}"
        model = httpx.get(f"{designer}/versions/{cfg.version_id}", timeout=5).json()["model"]
        port = 8010 + len(self.engines)
        self.engines[(cfg.pathway, cfg.version)] = port
        store = Store(make_engine(sqlite(cfg.schema)))
        self.serve(
            f"engine {cfg.pathway} v{cfg.version}",
            engine_app(Pathway.from_dict(model), store, self.bus),
            port,
        )
        return f"http://localhost:{port}"

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
    log.info("Ready. Deploy a published pathway (as admin) to start its engine. Ctrl-C stops everything.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stack.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
