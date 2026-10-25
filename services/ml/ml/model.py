"""Loading the trained urgency model and predicting with reasons (ML-02, C2-04).

The model file (joblib) holds the calibrated classifier, the uncalibrated model the
explanations come from, a small background sample for SHAP, the feature list and the
version. A prediction returns the level (1..5), a probability for each level, the
confidence (the highest probability), the top three reasons and the model version.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ml.features import BINARY, FEATURES, LABELS, features


@dataclass(frozen=True)
class Prediction:
    level: int
    probabilities: dict[int, float]
    confidence: float
    reasons: list[str]
    model_version: str

    def summary(self) -> str:
        """One line for the nurse: the model's suggestion and why."""
        return f"ML {self.model_version}: level {self.level} ({self.confidence:.0%}); " + "; ".join(
            self.reasons
        )


class UrgencyModel:
    def __init__(self, artifact: dict[str, Any]) -> None:
        self.version: str = artifact["version"]
        self.features: tuple[str, ...] = tuple(artifact["features"])
        if self.features != FEATURES:
            raise ValueError("model file was trained with different features")
        self.classes: list[int] = [int(c) for c in artifact["classes"]]
        self.model = artifact["model"]
        self.base = artifact["explainer_model"]
        self.metrics: dict[str, Any] = artifact.get("metrics", {})
        self.urgent_threshold: float = float(artifact.get("urgent_threshold", 0.5))
        self.trained_on: str = artifact.get("trained_on", "")
        self._explainer = self._make_explainer(artifact["background"])

    @classmethod
    def load(cls, path: str | Path) -> UrgencyModel:
        return cls(joblib.load(path))  # our own artifact from training.train  # nosec B301

    def _make_explainer(self, background: np.ndarray) -> Any:
        import shap

        try:
            return shap.TreeExplainer(self.base)
        except Exception:  # not a tree model: explain the probability function directly
            return shap.Explainer(self.base.predict_proba, background)

    def predict(self, inputs: Mapping[str, Any]) -> Prediction:
        x = np.array([features(inputs)], dtype=float)
        probs = self.model.predict_proba(x)[0]
        best = self.decide(probs)
        return Prediction(
            level=self.classes[best],
            probabilities={c: round(float(p), 4) for c, p in zip(self.classes, probs, strict=True)},
            confidence=round(float(probs[best]), 4),
            reasons=self.reasons(x, best),
            model_version=self.version,
        )

    def decide(self, probs: np.ndarray) -> int:
        """Index of the chosen level: urgent (1–2) when P(1) + P(2) reaches the tuned threshold
        (missing an urgent patient is the worst error), otherwise the likeliest of 3–5."""
        if probs[0] + probs[1] >= self.urgent_threshold:
            return int(np.argmax(probs[:2]))
        return 2 + int(np.argmax(probs[2:]))

    def reasons(self, x: np.ndarray, class_index: int, top: int = 3) -> list[str]:
        """The three features that pushed most towards the predicted level (SHAP values)."""
        values = self._shap_for(x, class_index)
        order = np.argsort(-values)[:top]
        out = []
        for i in order:
            if values[i] <= 0:
                break
            name, raw = self.features[i], x[0, i]
            if name in BINARY:  # a yes/no feature reads as its name: "chest complaint"
                out.append(LABELS[name])
            else:
                out.append(f"{LABELS[name]} {'missing' if math.isnan(raw) else f'{raw:g}'}")
        return out or ["no single feature stood out"]

    def _shap_for(self, x: np.ndarray, class_index: int) -> np.ndarray:
        sv = self._explainer(x)
        values = np.asarray(sv.values)  # (1, features) or (1, features, classes)
        if values.ndim == 3:
            return np.asarray(values[0, :, class_index])
        return np.asarray(values[0])
