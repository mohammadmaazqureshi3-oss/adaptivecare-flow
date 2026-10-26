"""scores service: clinical scores as pathway tasks (CLN-04, NFR-MNT-03).

A new task type added as a new service: it answers ``TaskRequested.News2Score`` with
the NEWS2 early warning score. The engine needed no change: a pathway names the service
in a task node, the engine publishes the request to ``TaskRequested.<service>``, and any
service bound to that key can answer, as the ml and patient services already do.

Missing observations are a permanent failure (the pathway's fallback asks a nurse);
anything else unexpected is temporary, so the engine retries. Stateless: a reply's id is
derived from its request's, so redelivery is harmless.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from care_events import Bus, Event
from care_events.rabbit import RabbitBus
from fastapi import FastAPI
from service_metrics import instrument

from scores.news2 import news2

log = logging.getLogger("scores")
BINDINGS = ["TaskRequested.News2Score"]


def outputs_for(request: Event, known: dict[str, Any]) -> dict[str, Any]:
    """Fill exactly the outputs the pathway declared, by name."""
    return {o["name"]: known[o["name"]] for o in request.payload.get("outputs", []) if o["name"] in known}


class Scorer:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus

    def on_event(self, request: Event) -> None:
        try:
            result = news2(request.payload.get("inputs", {}))
        except ValueError as exc:  # missing or unreadable observations: retrying will not help
            self.bus.publish(request.reply("TaskFailed", {"reason": str(exc), "temporary": False}))
            return
        except Exception as exc:  # a bug must not lose the task: the engine retries
            log.exception("NEWS2 failed")
            self.bus.publish(
                request.reply("TaskFailed", {"reason": f"NEWS2 failed: {exc}", "temporary": True})
            )
            return
        known = {"news2": result.score, "news2_risk": result.risk, "news2_note": result.note()}
        payload = {"outputs": outputs_for(request, known), "points": result.points}
        self.bus.publish(request.reply("TaskCompleted", payload))


def create_app(bus: Bus | None = None) -> FastAPI:
    owns_bus = bus is None
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    the_bus.subscribe("scores", BINDINGS, Scorer(the_bus).on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()

    app = FastAPI(title="AdaptiveCare scores", version="0.7.0", lifespan=lifespan)
    app.state.metrics = instrument(app, "scores")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "scores", "tasks": BINDINGS}

    return app
