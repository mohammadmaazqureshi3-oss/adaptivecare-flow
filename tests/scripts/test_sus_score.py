"""NFR-USE-02: the SUS scoring used for the alpha test."""

from __future__ import annotations

from pathlib import Path

import pytest
from sus_score import read, summary, sus


@pytest.mark.parametrize(
    "answers,score",
    [
        ([5, 1, 5, 1, 5, 1, 5, 1, 5, 1], 100.0),  # best possible
        ([1, 5, 1, 5, 1, 5, 1, 5, 1, 5], 0.0),  # worst possible
        ([3] * 10, 50.0),  # neutral
        ([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], 75.0),
    ],
)
def test_nfr_use02_sus_scoring(answers: list[int], score: float) -> None:
    assert sus(answers) == score


@pytest.mark.parametrize("answers", [[3] * 9, [0, 3, 3, 3, 3, 3, 3, 3, 3, 3], [6] + [3] * 9])
def test_nfr_use02_invalid_answers_are_refused(answers: list[int]) -> None:
    with pytest.raises(ValueError):
        sus(answers)


def test_nfr_use02_summary_from_csv(tmp_path: Path) -> None:
    f = tmp_path / "sus.csv"
    f.write_text(
        "participant,role,q1,q2,q3,q4,q5,q6,q7,q8,q9,q10\n"
        "p1,nurse,4,2,4,2,4,2,4,2,4,2\n"
        "p2,designer,5,1,5,1,5,1,5,1,5,1\n"
        "p3,nurse,3,3,3,3,3,3,3,3,3,3\n"
    )
    s = summary(read(f))
    assert s.n == 3 and s.mean == 75.0 and s.met
    assert s.by_role == {"designer": 100.0, "nurse": 62.5}
    assert s.low < 75.0 < s.high
