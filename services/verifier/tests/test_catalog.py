"""The catalog of small pathways with known answers: one per error type plus sound ones.

Test names carry story IDs (VER-01..06) for traceability.
"""

from __future__ import annotations

from builders import load, pw
from pathway_core import TokenGraph
from verifier.algorithm import verify


def test_ver01_imaging_deadlock_matches_the_worked_example() -> None:
    r = verify(load("imaging_deadlock"))
    assert r.status == "UNSAFE"
    assert r.states_explored == 6
    [dl] = [e for e in r.errors if e.type == "deadlock"]
    assert dl.nodes == ["wait_both"]
    assert [mv.node for mv in dl.path] == ["register", "imaging_type", "xray"]


def test_ver01_replacing_the_join_with_a_merge_is_safe() -> None:
    assert verify(load("imaging_fixed")).status == "SAFE"


def test_triage_pathway_is_safe() -> None:
    r = verify(load("triage"))
    assert r.status == "SAFE", r.to_dict()


def test_ver02_duplicate_work() -> None:
    p = pw("s:start p:and_split a:task b:task m:xor_merge c:task e:end", "s>p p>a p>b a>m b>m m>c c>e")
    assert "duplicate_work" in verify(p).types()


def test_ver02_unfinished_case() -> None:
    p = pw("s:start p:and_split a:task b:task e:end", "s>p p>a p>b a>e b>e")
    r = verify(p)
    assert "unfinished_case" in r.types()
    assert "deadlock" not in r.types()


def test_ver02_loop_with_no_exit_cannot_finish() -> None:
    p = pw("s:start m:xor_merge a:task x:xor_split e:end", "s>m m>a a>x x>m x>m?true")
    r = verify(p)
    assert "cannot_finish" in r.types()
    [cf] = [e for e in r.errors if e.type == "cannot_finish"]
    assert cf.path == []  # the case is doomed from the start


def test_sound_loop_is_safe() -> None:
    p = pw("s:start m:xor_merge a:task x:xor_split e:end", "s>m m>a a>x x>e x>m?true")
    assert verify(p).status == "SAFE"


def test_ver03_dead_step() -> None:
    p = pw("s:start a:task m:xor_merge orphan:task e:end", "s>a a>m orphan>m m>e")
    r = verify(p)
    assert any(e.type == "dead_step" and e.nodes == ["orphan"] for e in r.errors)


def test_ver04_missing_data_names_the_step_and_variable() -> None:
    p = pw(
        "s:start x:xor_split lab:task skip:task m:xor_merge review:task e:end",
        "s>x x>lab x>skip?urgent m>review lab>m skip>m review>e",
        variables={"urgent": "bool", "lab_result": "int"},
        s={"inputs": ["urgent"]},
        lab={"outputs": ["lab_result"]},
        review={"inputs": ["lab_result"]},
    )
    r = verify(p)
    [md] = [e for e in r.errors if e.type == "missing_data"]
    assert md.nodes == ["review"] and "lab_result" in md.message


def test_ver04_parallel_join_unites_branch_outputs() -> None:
    p = pw(
        "s:start p:and_split a:task b:task j:and_join c:task e:end",
        "s>p p>a p>b a>j b>j j>c c>e",
        variables={"x": "int", "y": "int"},
        a={"outputs": ["x"]},
        b={"outputs": ["y"]},
        c={"inputs": ["x", "y"]},
    )
    assert verify(p).status == "SAFE"


def test_ver04_fallback_does_not_set_the_failed_tasks_outputs() -> None:
    p = pw(
        "s:start predict:task manual:task m:xor_merge use:task e:end",
        "s>predict predict>m manual>m m>use use>e",
        variables={"urgency": "int"},
        predict={"kind": "ml", "outputs": ["urgency"], "fallback": "manual"},
        use={"inputs": ["urgency"]},
    )
    r = verify(p)
    assert [e.nodes for e in r.errors if e.type == "missing_data"] == [["use"]]


def test_ver05_condition_type_error() -> None:
    p = pw(
        "s:start x:xor_split a:task b:task m:xor_merge e:end",
        "s>x x>a x>b?urgency<'high' a>m b>m m>e",
        variables={"urgency": "int"},
        s={"inputs": ["urgency"]},
    )
    r = verify(p)
    [te] = [e for e in r.errors if e.type == "type_error"]
    assert te.edge is not None and "cannot compare" in te.message


def test_ver05_condition_syntax_error_has_a_position() -> None:
    p = pw(
        "s:start x:xor_split a:task b:task m:xor_merge e:end",
        "s>x x>a x>b?urgency<= a>m b>m m>e",
        variables={"urgency": "int"},
        s={"inputs": ["urgency"]},
    )
    [se] = [e for e in verify(p).errors if e.type == "syntax_error"]
    assert se.pos == 9


def test_ver06_too_large_reports_statistics() -> None:
    branches = " ".join(f"b{i}:task" for i in range(6))
    arrows = " ".join(f"p>b{i} b{i}>j" for i in range(6))
    p = pw(f"s:start p:and_split {branches} j:and_join e:end", f"s>p {arrows} j>e")
    r = verify(p, limit=10)
    assert r.status == "TOO_LARGE" and r.states_explored == 10


def test_structure_errors() -> None:
    no_default = pw("s:start x:xor_split a:task e:end", "s>x x>a?true x>e?true a>e")
    assert any("default" in e.message for e in verify(no_default).errors)
    no_start = pw("a:task e:end", "a>e")
    r = verify(no_start)
    assert r.status == "UNSAFE" and r.types() == {"structure"}


def test_every_counterexample_replays_to_its_state() -> None:
    for name in ("imaging_deadlock",):
        p = load(name)
        g = TokenGraph(p)
        for err in verify(p).errors:
            if err.type == "deadlock":
                m = g.replay(err.path)
                assert not g.enabled_moves(m) and not g.is_complete(m)
