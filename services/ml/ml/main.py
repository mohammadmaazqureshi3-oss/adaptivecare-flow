"""ml service: urgency prediction as a pathway task (C2-04).

Sprint 3 placeholder: the model is trained in Sprint 6 (ML-01/02). Until then every
``TaskRequested.PredictUrgency`` is answered with a permanent ``TaskFailed`` that says
so, which sends the Triage pathway down the manual-triage fallback the designer drew.
It never invents a prediction.

Stateless: the reply's id is derived from the request's, so a redelivered request
produces the same reply and the engine drops the copy.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from care_events import Bus, Event
from care_events.rabbit import RabbitBus
from fastapi import FastAPI

MODEL_VERSION = None  # set when ML-01 delivers a trained model


class Predictor:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus

    def on_event(self, request: Event) -> None:
        reason = "the urgency model is not available yet (arrives in Sprint 6, ML-01/02)"
        self.bus.publish(request.reply("TaskFailed", {"reason": reason, "temporary": False}))


def create_app(bus: Bus | None = None) -> FastAPI:
    owns_bus = bus is None
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    predictor = Predictor(the_bus)
    the_bus.subscribe("ml", ["TaskRequested.PredictUrgency"], predictor.on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()

    app = FastAPI(title="AdaptiveCare ml", version="0.3.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str | None]:
        return {"status": "ok", "service": "ml", "model_version": MODEL_VERSION}

    return app
