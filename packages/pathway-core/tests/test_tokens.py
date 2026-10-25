"""Test-first unit tests for each of the eight token rules (Sprint 2, VER-01..02)."""

from __future__ import annotations

import pytest
from pathway_core import Pathway, TokenGraph


def build(nodes: list[tuple[str, str]], edges: list[tuple[str, str]], **extra: dict) -> TokenGraph:
    """Small pathway from (id, type) pairs; a decision's first branch is its default."""
    types = dict(nodes)
    seen_split: set[str] = set()
    edge_docs = []
    for a, b in edges:
        doc = {"id": f"{a}-{b}", "from": a, "to": b}
        if types.get(a) == "xor_split":
            if a in seen_split:
                doc["condition"] = "true"
            else:
                doc["default"] = True
                seen_split.add(a)
        edge_docs.append(doc)
    node_docs = [
        {"id": i, "type": t, **({"kind": "human"} if t == "task" else {}), **extra.get(i, {})}
        for i, t in nodes
    ]
    return TokenGraph(Pathway.from_dict({"id": "t", "nodes": node_docs, "edges": edge_docs}))


def marking(g: TokenGraph, *edge_ids: str) -> tuple[int, ...]:
    m = list(g.empty())
    for e in edge_ids:
        m[g.index[e]] += 1
    return tuple(m)


def test_rule1_start_puts_one_token_on_its_outgoing_arrow() -> None:
    g = build([("s", "start"), ("e", "end")], [("s", "e")])
    assert g.initial_marking() == marking(g, "s-e")


def test_rule2_task_moves_the_token_on() -> None:
    g = build([("s", "start"), ("a", "task"), ("e", "end")], [("s", "a"), ("a", "e")])
    [(mv, m2)] = g.successors(g.initial_marking())
    assert mv.node == "a" and m2 == marking(g, "a-e")


def test_rule3_decision_gives_one_move_per_branch() -> None:
    g = build(
        [("s", "start"), ("x", "xor_split"), ("a", "task"), ("b", "task"), ("e", "end")],
        [("s", "x"), ("x", "a"), ("x", "b"), ("a", "e"), ("b", "e")],
    )
    # Start's token already sits on the arrow into the decision.
    results = {m2 for _, m2 in g.successors(g.initial_marking())}
    assert results == {marking(g, "x-a"), marking(g, "x-b")}


def test_rule4_merge_passes_on_each_arriving_token() -> None:
    g = build(
        [("s", "start"), ("p", "and_split"), ("m", "xor_merge"), ("e", "end")],
        [("s", "p"), ("p", "m"), ("m", "e")],
    )
    two = marking(g, "p-m", "p-m")
    moves = g.enabled_moves(two)
    assert [mv.node for mv in moves] == ["m"]
    assert g.fire(two, moves[0]) == marking(g, "p-m", "m-e")


def test_rule5_parallel_split_starts_every_branch() -> None:
    g = build(
        [("s", "start"), ("p", "and_split"), ("a", "task"), ("b", "task"), ("j", "and_join"), ("e", "end")],
        [("s", "p"), ("p", "a"), ("p", "b"), ("a", "j"), ("b", "j"), ("j", "e")],
    )
    [(_, m2)] = g.successors(g.initial_marking())
    assert m2 == marking(g, "p-a", "p-b")


def test_rule6_join_waits_for_every_incoming_branch() -> None:
    g = build(
        [("s", "start"), ("p", "and_split"), ("a", "task"), ("b", "task"), ("j", "and_join"), ("e", "end")],
        [("s", "p"), ("p", "a"), ("p", "b"), ("a", "j"), ("b", "j"), ("j", "e")],
    )
    half = marking(g, "a-j", "p-b")
    assert "j" not in [mv.node for mv in g.enabled_moves(half)]
    both = marking(g, "a-j", "b-j")
    [mv] = g.enabled_moves(both)
    assert mv.node == "j" and g.fire(both, mv) == marking(g, "j-e")


def test_rule7_timer_passes_the_token_on() -> None:
    g = build([("s", "start"), ("t", "timer"), ("e", "end")], [("s", "t"), ("t", "e")], t={"minutes": 5})
    [(mv, m2)] = g.successors(g.initial_marking())
    assert mv.node == "t" and m2 == marking(g, "t-e")


def test_rule8_end_takes_the_token_and_the_case_is_complete() -> None:
    g = build([("s", "start"), ("e", "end")], [("s", "e")])
    [(mv, m2)] = g.successors(g.initial_marking())
    assert mv.node == "e" and g.is_complete(m2)


def test_task_with_fallback_can_complete_or_take_the_fallback() -> None:
    g = build(
        [("s", "start"), ("a", "task"), ("f", "task"), ("m", "xor_merge"), ("e", "end")],
        [("s", "a"), ("a", "m"), ("f", "m"), ("m", "e")],
        a={"fallback": "f"},
    )
    produced = {mv.produced for mv in g.enabled_moves(g.initial_marking())}
    assert produced == {("a-m",), ("a~>f",)}


def test_fire_rejects_a_move_that_is_not_enabled() -> None:
    g = build([("s", "start"), ("a", "task"), ("e", "end")], [("s", "a"), ("a", "e")])
    [mv] = g.enabled_moves(g.initial_marking())
    with pytest.raises(ValueError):
        g.fire(g.empty(), mv)


def test_replay_rebuilds_the_marking() -> None:
    g = build([("s", "start"), ("a", "task"), ("e", "end")], [("s", "a"), ("a", "e")])
    path = []
    m = g.initial_marking()
    while moves := g.enabled_moves(m):
        path.append(moves[0])
        m = g.fire(m, moves[0])
    assert g.replay(path) == m and g.is_complete(m)
