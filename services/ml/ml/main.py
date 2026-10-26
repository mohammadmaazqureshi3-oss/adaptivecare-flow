"""ml service: urgency prediction as a pathway task (ML-02, C2-04).

Loads the model file at start-up and answers every ``TaskRequested.PredictUrgency`` with
``TaskCompleted``: the outputs the pathway declared (``urgency``, ``confidence`` and a
``triage_note`` with the top reasons), plus all probabilities, the reasons and the model
version in the payload. Safety lives in the pathway, not here: low oxygen or pressure and
low confidence route to a nurse whatever the model says, and a nurse always confirms.

Without a model file it answers with a permanent ``TaskFailed``, so the pathway takes the
manual-triage fallback; a prediction error is temporary, so the engine retries.

Stateless: a reply's id is derived from its request's, so redelivery is harmless.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from care_events import Bus, Event
from care_events.rabbit import RabbitBus
from fastapi import FastAPI
from service_metrics import instrument

from ml.model import Prediction, UrgencyModel

log = logging.getLogger("ml")
DEFAULT_MODEL = Path(__file__).resolve().parents[1] / "models" / "urgency-v1.joblib"


def load_model(path: str | Path | None = None) -> UrgencyModel | None:
    path = Path(path or os.environ.get("MODEL_PATH") or DEFAULT_MODEL)
    if not path.exists():
        log.warning("no model file at %s: PredictUrgency will fail over to manual triage", path)
        return None
    return UrgencyModel.load(path)


def outputs_for(request: Event, p: Prediction) -> dict[str, Any]:
    """Fill exactly the outputs the pathway asked for, by name."""
    known = {"urgency": p.level, "confidence": p.confidence, "triage_note": p.summary()}
    return {o["name"]: known[o["name"]] for o in request.payload.get("outputs", []) if o["name"] in known}


class Predictor:
    def __init__(self, bus: Bus, model: UrgencyModel | None) -> None:
        self.bus, self.model = bus, model

    def on_event(self, request: Event) -> None:
        if self.model is None:
            reason = "no urgency model is installed (run services/ml/training/train.py)"
            self.bus.publish(request.reply("TaskFailed", {"reason": reason, "temporary": False}))
            return
        try:
            p = self.model.predict(request.payload.get("inputs", {}))
        except Exception as exc:  # a broken input must not lose the task: the engine retries
            log.exception("prediction failed")
            self.bus.publish(
                request.reply("TaskFailed", {"reason": f"prediction failed: {exc}", "temporary": True})
            )
            return
        payload = {
            "outputs": outputs_for(request, p),
            "probabilities": p.probabilities,
            "reasons": p.reasons,
            "model_version": p.model_version,
        }
        self.bus.publish(request.reply("TaskCompleted", payload))


def create_app(bus: Bus | None = None, model_path: str | Path | None = None) -> FastAPI:
    owns_bus = bus is None
    the_bus: Bus = bus or RabbitBus(os.environ["AMQP_URL"])
    predictor = Predictor(the_bus, load_model(model_path))
    the_bus.subscribe("ml", ["TaskRequested.PredictUrgency"], predictor.on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_bus:
            the_bus.start()
        yield
        if owns_bus:
            the_bus.stop()

    app = FastAPI(title="AdaptiveCare ml", version="0.6.0", lifespan=lifespan)
    app.state.metrics = instrument(app, "ml")
    app.state.predictor = predictor

    @app.get("/health")
    def health() -> dict[str, Any]:
        m = predictor.model
        return {
            "status": "ok",
            "service": "ml",
            "model_version": m.version if m else None,
            "trained_on": m.trained_on if m else None,
        }

    return app
