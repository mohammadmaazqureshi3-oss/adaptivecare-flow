"""NFR-USE-02: score the alpha test's System Usability Scale answers (target: mean >= 70).

    .venv/bin/python scripts/sus_score.py docs/alpha-test/sus-results.csv

The CSV has one row per participant: ``participant,role,q1,...,q10`` with answers 1–5
(1 = strongly disagree). SUS (Brooke, 1996): odd items count ``answer - 1``, even items
``5 - answer``; the sum times 2.5 gives 0–100. The report gives every score, the mean
with a 95% confidence interval, the mean per role, and whether the target is met.
"""

from __future__ import annotations

import csv
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from scipy.stats import t as student_t

TARGET = 70.0
ITEMS = [f"q{i}" for i in range(1, 11)]


@dataclass(frozen=True)
class Answer:
    participant: str
    role: str
    score: float


def sus(answers: list[int]) -> float:
    """One questionnaire's SUS score."""
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        raise ValueError("SUS needs ten answers from 1 to 5")
    odd = sum(a - 1 for a in answers[0::2])
    even = sum(5 - a for a in answers[1::2])
    return (odd + even) * 2.5


def read(path: Path) -> list[Answer]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    try:
        return [Answer(r["participant"], r["role"], sus([int(r[q]) for q in ITEMS])) for r in rows]
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"{path}: {exc}") from exc


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float
    low: float  # 95% confidence interval
    high: float
    by_role: dict[str, float]

    @property
    def met(self) -> bool:
        return self.mean >= TARGET


def summary(answers: list[Answer]) -> Summary:
    scores = [a.score for a in answers]
    mean = statistics.fmean(scores)
    half = math.inf
    if len(scores) > 1:
        half = (
            float(student_t.ppf(0.975, len(scores) - 1)) * statistics.stdev(scores) / math.sqrt(len(scores))
        )
    by_role: dict[str, list[float]] = {}
    for a in answers:
        by_role.setdefault(a.role, []).append(a.score)
    roles = {role: statistics.fmean(s) for role, s in sorted(by_role.items())}
    return Summary(len(scores), mean, mean - half, mean + half, roles)


def main() -> None:
    answers = read(Path(sys.argv[1]))
    if not answers:
        raise SystemExit("no answers yet")
    for a in answers:
        print(f"{a.participant:>12} {a.role:>13} {a.score:6.1f}")
    s = summary(answers)
    print(f"\nSUS mean {s.mean:.1f} (95% CI {s.low:.1f}–{s.high:.1f}, n = {s.n})")
    for role, mean in s.by_role.items():
        print(f"  {role}: {mean:.1f}")
    print(f"NFR-USE-02 target {TARGET:.0f}: {'met' if s.met else 'NOT met'}")


if __name__ == "__main__":
    main()
