"""Training data for the urgency model (ML-01, plan Section 11).

* ``load_ktas(path)`` reads the Korean triage study's file (Moon et al., PLoS ONE 2019:
  1,267 adult records, 24 features; semicolon-separated, decimal commas). The label is
  ``KTAS_expert`` (1 most urgent … 5 least).
* ``synthetic(n, seed)`` is the documented fallback when no licensed file is available
  (risk R6): physiology drawn from each urgency level with noise and deliberate label
  ambiguity. Results on it prove the pipeline, not clinical accuracy.

Both return rows of pathway-style inputs (the same keys the Triage pathway sends) and labels.
"""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

# Level mix of the synthetic data, close to published ED distributions (levels 1–2 are rare).
SYNTHETIC_MIX = {1: 0.03, 2: 0.14, 3: 0.40, 4: 0.33, 5: 0.10}
KTAS_ARRIVAL = {
    1: "walk_in",
    2: "ambulance",
    3: "walk_in",
    4: "ambulance",
    5: "referral",
    6: "other",
    7: "other",
}
COMPLAINTS = {  # (complaint, relative weight) by level
    1: [
        ("chest pain, sweating", 3),
        ("shortness of breath, cyanosis", 3),
        ("unresponsive after fall", 2),
        ("seizure", 2),
    ],
    2: [
        ("chest pain", 4),
        ("shortness of breath", 3),
        ("abdominal pain, vomiting", 2),
        ("sudden weakness", 2),
        ("fever, confusion", 1),
    ],
    3: [
        ("abdominal pain", 4),
        ("fever", 3),
        ("headache", 2),
        ("dizziness", 2),
        ("fall, wrist fracture", 2),
        ("cough, breath", 1),
    ],
    4: [
        ("ankle injury", 3),
        ("cut on hand", 2),
        ("back pain", 2),
        ("sore throat", 2),
        ("headache", 1),
        ("nausea", 1),
    ],
    5: [("prescription renewal", 3), ("minor rash", 2), ("insect bite", 2), ("wound check", 2), ("cough", 1)],
}


def _num(text: str) -> float:
    text = (text or "").strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return math.nan


def _int(text: str) -> int:
    """A whole number, or 0 for anything unreadable (NaN counts as true, so `or 0` is not enough)."""
    value = _num(text)
    return 0 if math.isnan(value) else int(value)


def load_ktas(path: str | Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Rows and expert KTAS levels from the study's CSV (impossible values become missing)."""
    rows, labels = [], []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            level = _int(r.get("KTAS_expert", ""))
            if level not in (1, 2, 3, 4, 5):
                continue
            rows.append(
                {
                    "age": _num(r.get("Age", "")),
                    "sex": {"1": "female", "2": "male"}.get((r.get("Sex") or "").strip(), ""),
                    "arrival_mode": KTAS_ARRIVAL.get(_int(r.get("Arrival mode", "")), "other"),
                    "chief_complaint": r.get("Chief_complain", ""),
                    "mental": _num(r.get("Mental", "")),
                    "pain": _num(r.get("NRS_pain", "")),
                    "sbp": _clean(_num(r.get("SBP", "")), 40, 260),
                    "hr": _clean(_num(r.get("HR", "")), 20, 250),
                    "rr": _clean(_num(r.get("RR", "")), 4, 60),
                    "temp": _clean(_num(r.get("BT", "")), 30, 43),
                    "spo2": _clean(_num(r.get("Saturation", "")), 50, 100),
                }
            )
            labels.append(level)
    return rows, labels


def _clean(value: float, low: float, high: float) -> float:
    """Step 1 of training: impossible values are treated as missing."""
    return value if low <= value <= high else math.nan


def synthetic(n: int, seed: int = 7) -> tuple[list[dict[str, Any]], list[int]]:
    """``n`` synthetic triage records with levels 1..5 (see module docstring)."""
    rng = random.Random(seed)  # noqa: S311 (reproducible synthetic data, not security)  # nosec B311
    levels = rng.choices(list(SYNTHETIC_MIX), weights=list(SYNTHETIC_MIX.values()), k=n)
    rows, labels = [], []
    for level in levels:
        rows.append(_record(level, rng))
        # Real triage is ambiguous: about 10% of records sit one level away from their physiology.
        ambiguous = rng.random() < 0.10
        labels.append(min(5, max(1, level + rng.choice((-1, 1)))) if ambiguous else level)
    return rows, labels


def _record(level: int, rng: random.Random) -> dict[str, Any]:
    s = (5 - level) / 4  # severity 0 (level 5) .. 1 (level 1)
    texts, weights = zip(*COMPLAINTS[level], strict=True)
    mental = 1 if rng.random() > 0.55 * s**3 else rng.choice((2, 3, 4))
    record = {
        "age": max(18, min(98, round(rng.gauss(45 + 18 * s, 18)))),
        "sex": rng.choice(("female", "male")),
        "arrival_mode": "ambulance"
        if rng.random() < 0.08 + 0.55 * s
        else rng.choice(("walk_in", "walk_in", "referral")),
        "chief_complaint": rng.choices(texts, weights=weights)[0],
        "mental": mental,
        "pain": max(0, min(10, round(rng.gauss(2.5 + 4.5 * s, 2)))),
        "sbp": round(rng.gauss(128 - 22 * s * rng.choice((1, 1, -0.6)), 14)),
        "hr": round(rng.gauss(78 + 32 * s, 12)),
        "rr": round(rng.gauss(16 + 9 * s, 2.5)),
        "temp": round(rng.gauss(36.8 + 0.9 * s * rng.random(), 0.45), 1),
        "spo2": min(100, round(rng.gauss(98 - 9 * s**2, 1.8))),
    }
    if rng.random() < 0.05:
        record["spo2"] = math.nan  # often missing in real ED data
    return record
