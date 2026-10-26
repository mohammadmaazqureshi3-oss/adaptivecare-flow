"""DES-04: deadlines, escalation chains, retries, fallback branches and undo actions on tasks.

Partition and boundary tests on each setting, and the typed values the Engine and
Simulator will read.
"""

from __future__ import annotations

from typing import Any

import pytest
from pathway_core import Node
from pathway_core.settings import deadline, duration, response_timeout, retry, settings_issues, undo


def task(kind: str = "service", **settings: Any) -> Node:
    who = {"role": "nurse"} if kind == "human" else {"service": "Lab"}
    return Node(id="t", type="task", kind=kind, settings=settings, **who)


def test_a_task_with_no_policies_is_fine() -> None:
    assert settings_issues(task()) == []


@pytest.mark.parametrize(
    "node,fragment",
    [
        (Node(id="t", type="task", kind="human"), "needs the role"),
        (Node(id="t", type="task", kind="human", role="  "), "needs the role"),
        (Node(id="t", type="task", kind="service"), "service task needs the service"),
        (Node(id="t", type="task", kind="ml"), "ML task needs the service"),
    ],
)
def test_des04_who_does_the_task(node: Node, fragment: str) -> None:
    assert any(fragment in i for i in settings_issues(node))


# ---- deadline and escalation ----------------------------------------------------


def test_des04_valid_deadline_with_escalation_chain() -> None:
    d = {
        "minutes": 10,
        "escalation": [{"role": "charge_nurse", "afterMin": 5}, {"role": "doctor", "afterMin": 5}],
    }
    n = task("human", deadline=d)
    assert settings_issues(n) == []
    dl = deadline(n)
    assert dl is not None and dl.minutes == 10
    assert [(e.role, e.after_min) for e in dl.escalation] == [("charge_nurse", 5.0), ("doctor", 5.0)]


@pytest.mark.parametrize(
    "d,fragment",
    [
        ({"minutes": 0}, "more than 0 minutes"),  # boundary
        ({"minutes": -5}, "more than 0 minutes"),
        ({"minutes": "ten"}, "more than 0 minutes"),
        ({"minutes": 10, "escalation": [{"role": "", "afterMin": 5}]}, "level 1 needs a role"),
        (
            {"minutes": 10, "escalation": [{"role": "a", "afterMin": 5}, {"role": "b", "afterMin": 0}]},
            "level 2 needs a wait",
        ),
    ],
)
def test_des04_invalid_deadlines(d: dict, fragment: str) -> None:
    assert any(fragment in i for i in settings_issues(task("human", deadline=d)))


def test_smallest_valid_deadline() -> None:
    assert settings_issues(task("human", deadline={"minutes": 0.5, "escalation": []})) == []


# ---- retries -----------------------------------------------------------------------


@pytest.mark.parametrize("r", [{"max": 1, "baseDelayS": 0.5}, {"max": 10, "baseDelayS": 3600}])
def test_des04_retry_boundaries_accepted(r: dict) -> None:
    assert settings_issues(task(retry=r)) == []


@pytest.mark.parametrize(
    "r,fragment",
    [
        ({"max": 0, "baseDelayS": 1}, "between 1 and 10"),
        ({"max": 11, "baseDelayS": 1}, "between 1 and 10"),
        ({"max": 2.5, "baseDelayS": 1}, "between 1 and 10"),
        ({"max": 2, "baseDelayS": 0}, "retry delay"),
        ({"max": 2, "baseDelayS": 3601}, "retry delay"),
        ({"max": 2, "baseDelayS": 1, "timeoutS": 0}, "answer timeout"),
        ({"max": 2, "baseDelayS": 1, "timeoutS": 3601}, "answer timeout"),
        ({"max": 2, "baseDelayS": 1, "timeoutS": "soon"}, "answer timeout"),
    ],
)
def test_des04_retry_out_of_range(r: dict, fragment: str) -> None:
    assert any(fragment in i for i in settings_issues(task(retry=r)))


def test_des04_people_do_not_get_retries() -> None:
    assert any(
        "Retries apply to service and ML" in i
        for i in settings_issues(task("human", retry={"max": 2, "baseDelayS": 1}))
    )


def test_retry_backoff_doubles() -> None:
    r = retry(task(retry={"max": 3, "baseDelayS": 1}))
    assert r is not None and [r.delay(a) for a in (1, 2, 3)] == [1.0, 2.0, 4.0]


# ---- undo and duration ------------------------------------------------------------


def test_des04_undo_action() -> None:
    assert undo(task(undo="ReleaseBed")) == "ReleaseBed"
    assert undo(task()) is None
    assert any("undo action" in i for i in settings_issues(task(undo="  ")))


@pytest.mark.parametrize(
    "d,ok",
    [
        ({"dist": "lognormal", "meanMin": 6, "sdMin": 2}, True),
        ({"dist": "fixed", "meanMin": 0.1}, True),
        ({"dist": "triangular", "minMin": 1, "modeMin": 1, "maxMin": 4}, True),  # mode == min boundary
        ({"dist": "triangular", "minMin": 2, "modeMin": 2, "maxMin": 2}, False),  # min == max
        ({"dist": "triangular", "minMin": 3, "modeMin": 1, "maxMin": 4}, False),
        ({"dist": "lognormal", "meanMin": 6}, False),
        ({"dist": "exponential", "meanMin": 0}, False),
        ({"dist": "gamma", "meanMin": 3}, False),
        ({"dist": "fixed", "meanMin": -1}, False),
    ],
)
def test_duration_distributions(d: dict, ok: bool) -> None:
    assert (settings_issues(task(duration=d)) == []) is ok


def test_typed_duration() -> None:
    d = duration(task(duration={"dist": "triangular", "minMin": 1, "modeMin": 2, "maxMin": 4}))
    assert (
        d is not None
        and d.dist == "triangular"
        and d.params == {"minMin": 1.0, "modeMin": 2.0, "maxMin": 4.0}
    )


def test_timer_needs_a_positive_wait() -> None:
    assert settings_issues(Node(id="w", type="timer", minutes=0)) != []
    assert settings_issues(Node(id="w", type="timer", minutes=5)) == []


# ---- Sprint 6: End emits an event; override check (WRK-02) ----------------------------


@pytest.mark.parametrize(
    "name,ok", [("TriageCompleted", True), ("triageDone", False), ("A b", False), (None, True)]
)
def test_end_can_emit_a_well_named_event(name: str | None, ok: bool) -> None:
    from pathway_core.settings import emit

    node = Node(id="e", type="end", settings={} if name is None else {"emit": name})
    assert (settings_issues(node) == []) is ok
    assert emit(node) == name


def test_wrk02_override_check_names_an_input_and_an_output() -> None:
    from pathway_core.settings import override

    good = Node(
        id="c",
        type="task",
        kind="human",
        role="nurse",
        inputs=("urgency",),
        outputs=("confirmed",),
        settings={"override": {"suggested": "urgency", "decided": "confirmed"}},
    )
    assert settings_issues(good) == [] and override(good) is not None
    bad = Node(
        id="c",
        type="task",
        kind="human",
        role="nurse",
        inputs=("urgency",),
        outputs=("confirmed",),
        settings={"override": {"suggested": "confirmed", "decided": "urgency"}},
    )
    assert any("override check" in i for i in settings_issues(bad))


def test_nfr_rob01_which_tasks_get_an_answer_timeout() -> None:
    assert response_timeout(task(retry={"max": 2, "baseDelayS": 1})) == 30  # the default
    assert response_timeout(task(retry={"max": 2, "baseDelayS": 1, "timeoutS": 8})) == 8
    with_fallback = Node(id="t", type="task", kind="ml", service="M", fallback="manual")
    assert response_timeout(with_fallback) == 30
    assert response_timeout(task()) is None  # nowhere to go: it waits for the service
    assert response_timeout(task("human")) is None  # people get deadlines instead
