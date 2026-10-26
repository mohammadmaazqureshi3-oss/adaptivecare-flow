"""NEWS2, the National Early Warning Score 2 (Royal College of Physicians, 2017), SpO2 scale 1.

Seven observations each give 0–3 points; the total and any single 3 set the clinical
risk. Pure functions: no input is changed and nothing is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# (upper bound of the band, points), checked in order; the last band has no bound.
Bands = tuple[tuple[float, int], ...]
RESP_RATE: Bands = ((8, 3), (11, 1), (20, 0), (24, 2), (float("inf"), 3))
SPO2_SCALE1: Bands = ((91, 3), (93, 2), (95, 1), (float("inf"), 0))
SYSTOLIC: Bands = ((90, 3), (100, 2), (110, 1), (219, 0), (float("inf"), 3))
PULSE: Bands = ((40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (float("inf"), 3))
TEMPERATURE: Bands = ((35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (float("inf"), 2))
OXYGEN_POINTS = 2
NOT_ALERT_POINTS = 3
REQUIRED = ("rr", "spo2", "sbp", "hr", "temp", "mental")


def band(value: float, bands: Bands) -> int:
    return next(points for upper, points in bands if value <= upper)


@dataclass(frozen=True)
class News2:
    score: int
    risk: str  # low | low-medium | medium | high
    points: dict[str, int]

    def note(self) -> str:
        parts = ", ".join(f"{k} {v}" for k, v in self.points.items() if v)
        return f"NEWS2 {self.score} ({self.risk} risk)" + (f": {parts}" if parts else "")


def risk(score: int, any_three: bool) -> str:
    """RCP thresholds: 7+ high, 5–6 medium, a single 3 low-medium, else low."""
    if score >= 7:
        return "high"
    if score >= 5:
        return "medium"
    return "low-medium" if any_three else "low"


def alert(mental: Any) -> bool:
    """AVPU: only 'alert' scores 0; voice, pain, unresponsive or new confusion score 3."""
    return str(mental).strip().lower() in ("a", "alert")


def news2(obs: dict[str, Any]) -> News2:
    """Score one set of observations. Raises ``ValueError`` naming what is missing."""
    missing = [k for k in REQUIRED if obs.get(k) is None or obs.get(k) == ""]
    if missing:
        raise ValueError(f"NEWS2 needs {', '.join(missing)}")
    points = {
        "respiration": band(float(obs["rr"]), RESP_RATE),
        "SpO2": band(float(obs["spo2"]), SPO2_SCALE1),
        "oxygen": OXYGEN_POINTS if obs.get("oxygen") is True else 0,
        "systolic BP": band(float(obs["sbp"]), SYSTOLIC),
        "pulse": band(float(obs["hr"]), PULSE),
        "consciousness": 0 if alert(obs["mental"]) else NOT_ALERT_POINTS,
        "temperature": band(float(obs["temp"]), TEMPERATURE),
    }
    total = sum(points.values())
    return News2(total, risk(total, any(p == 3 for p in points.values())), points)
