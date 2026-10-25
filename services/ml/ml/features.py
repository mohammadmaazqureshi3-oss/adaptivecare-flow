"""The model's inputs: one place that turns triage data into a feature vector.

Used by training and by the prediction service, so the model sees the same features in
both. Inputs follow the Triage pathway's variables (age, sex, arrival mode, chief
complaint, vital signs, pain, mental state); anything missing becomes NaN and is imputed
by the model pipeline, as oxygen saturation often is in the KTAS data.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

FEATURES = (
    "age",
    "male",
    "arrival_ambulance",
    "arrival_referral",
    "mental",  # AVPU: 1 alert, 2 responds to voice, 3 to pain, 4 unresponsive
    "pain",  # 0..10
    "sbp",
    "hr",
    "rr",
    "temp",
    "spo2",
    "kw_chest",
    "kw_breath",
    "kw_abdomen",
    "kw_fever",
    "kw_trauma",
    "kw_neuro",
)

# Chief-complaint keywords (English and the KTAS file's common terms).
KEYWORDS = {
    "kw_chest": ("chest", "palpitation", "angina"),
    "kw_breath": ("breath", "dyspnea", "dyspnoea", "wheez", "asthma", "cough"),
    "kw_abdomen": ("abdom", "stomach", "vomit", "nausea", "epigastr", "diarr"),
    "kw_fever": ("fever", "chill", "febrile"),
    "kw_trauma": ("fall", "injur", "trauma", "fracture", "wound", "lacerat", "accident", "cut"),
    "kw_neuro": ("headache", "dizz", "seizure", "faint", "syncope", "weakness", "numb", "confus", "stroke"),
}
BINARY = frozenset({"male", "arrival_ambulance", "arrival_referral", *KEYWORDS})
LABELS = {
    "age": "age",
    "male": "male",
    "arrival_ambulance": "arrived by ambulance",
    "arrival_referral": "referred",
    "mental": "mental state",
    "pain": "pain score",
    "sbp": "systolic pressure",
    "hr": "heart rate",
    "rr": "breathing rate",
    "temp": "temperature",
    "spo2": "oxygen saturation",
    "kw_chest": "chest complaint",
    "kw_breath": "breathing complaint",
    "kw_abdomen": "abdominal complaint",
    "kw_fever": "fever",
    "kw_trauma": "injury",
    "kw_neuro": "neurological complaint",
}


def _number(value: Any) -> float:
    if value is None or value == "" or isinstance(value, bool):
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def mental_level(value: Any) -> float:
    """AVPU from a word or a number: alert/voice/pain/unresponsive → 1..4."""
    if isinstance(value, str) and value.strip():
        return float({"a": 1, "v": 2, "p": 3, "u": 4}.get(value.strip().lower()[0], math.nan))
    n = _number(value)
    return n if n in (1.0, 2.0, 3.0, 4.0) else math.nan


def _male(sex: str) -> float:
    return 1.0 if sex == "male" else 0.0 if sex == "female" else math.nan


def features(inputs: Mapping[str, Any]) -> list[float]:
    """The feature vector, in ``FEATURES`` order, for one patient."""
    complaint = str(inputs.get("chief_complaint") or "").lower()
    arrival = str(inputs.get("arrival_mode") or "").lower()
    sex = str(inputs.get("sex") or "").lower()
    row = {
        "age": _number(inputs.get("age")),
        "male": _male(sex),
        "arrival_ambulance": float("ambulance" in arrival),
        "arrival_referral": float("referral" in arrival),
        "mental": mental_level(inputs.get("mental")),
        "pain": _number(inputs.get("pain")),
        "sbp": _number(inputs.get("sbp")),
        "hr": _number(inputs.get("hr")),
        "rr": _number(inputs.get("rr")),
        "temp": _number(inputs.get("temp")),
        "spo2": _number(inputs.get("spo2")),
    }
    for kw, words in KEYWORDS.items():
        row[kw] = float(any(w in complaint for w in words))
    return [row[f] for f in FEATURES]
