"""Property-based tests (Hypothesis) on randomly generated block-structured pathways.

1. Every block-structured pathway (each split closed by a join of the same type) is SAFE.
2. Changing one join's type is always detected.
3. Every reported counterexample replays, with the token rules, to the reported state.
"""

from __future__ import annotations

import itertools
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pathway_core import Pathway, TokenGraph
from verifier.algorithm import verify

Block = Any  # ("task",) | ("seq"|"xor"|"and", [Block, ...]) | ("loop", Block)

blocks: st.SearchStrategy[Block] = st.recursive(
    st.just(("task",)),
    lambda inner: st.one_of(
        st.tuples(st.just("seq"), st.lists(inner, min_size=2, max_size=3)),
        st.tuples(st.just("xor"), st.lists(inner, min_size=2, max_size=3)),
        st.tuples(st.just("and"), st.lists(inner, min_size=2, max_size=3)),
        st.tuples(st.just("loop"), inner),
    ),
    max_leaves=8,
)


class _Builder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.joins: list[str] = []  # joins closing an xor or and block
        self.ids = itertools.count()
        self.needs_default: set[str] = set()
        self.has_default: set[str] = set()

    def node(self, ntype: str) -> str:
        nid = f"{ntype}{next(self.ids)}"
        doc: dict[str, Any] = {"id": nid, "type": ntype}
        if ntype == "task":
            doc["kind"], doc["role"] = "human", "nurse"
        self.nodes.append(doc)
        return nid

    def edge(self, a: str, b: str, back: bool = False) -> None:
        doc: dict[str, Any] = {"id": f"{a}>{b}#{len(self.edges)}", "from": a, "to": b}
        is_split = any(n["id"] == a and n["type"] == "xor_split" for n in self.nodes)
        if is_split:
            if back or a in self.has_default:
                doc["condition"] = "true"
            else:
                doc["default"] = True
                self.has_default.add(a)
        self.edges.append(doc)

    def emit(self, block: Block) -> tuple[str, str]:
        kind = block[0]
        if kind == "task":
            n = self.node("task")
            return n, n
        if kind == "seq":
            parts = [self.emit(b) for b in block[1]]
            for (_, out), (inn, _) in itertools.pairwise(parts):
                self.edge(out, inn)
            return parts[0][0], parts[-1][1]
        if kind == "loop":
            m, x = self.node("xor_merge"), self.node("xor_split")
            inn, out = self.emit(block[1])
            self.edge(m, inn)
            self.edge(out, x)
            self.edge(x, m, back=True)
            return m, x
        split_t, join_t = ("xor_split", "xor_merge") if kind == "xor" else ("and_split", "and_join")
        split, join = self.node(split_t), self.node(join_t)
        for b in block[1]:
            inn, out = self.emit(b)
            self.edge(split, inn)
            self.edge(out, join)
        self.joins.append(join)
        return split, join

    def pathway(self, block: Block) -> Pathway:
        s, e = self.node("start"), self.node("end")
        inn, out = self.emit(block)
        self.edge(s, inn)
        self.edge(out, e)
        return Pathway.from_dict({"id": "gen", "nodes": self.nodes, "edges": self.edges})


def build(block: Block) -> _Builder:
    b = _Builder()
    b.built = b.pathway(block)  # type: ignore[attr-defined]
    return b


SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(blocks)
def test_block_structured_pathways_are_safe(block: Block) -> None:
    p = build(block).built  # type: ignore[attr-defined]
    r = verify(p)
    assert r.status == "SAFE", (block, r.to_dict())


@SETTINGS
@given(blocks, st.data())
def test_changing_one_join_type_is_detected(block: Block, data: st.DataObject) -> None:
    b = build(block)
    if not b.joins:
        return
    target = data.draw(st.sampled_from(b.joins))
    doc = b.built.to_dict()  # type: ignore[attr-defined]
    for n in doc["nodes"]:
        if n["id"] == target:
            n["type"] = "xor_merge" if n["type"] == "and_join" else "and_join"
    p = Pathway.from_dict(doc)
    r = verify(p, limit=20_000)  # errors are found early; a smaller limit keeps the test fast
    assert r.status == "UNSAFE"
    assert r.types() & {"deadlock", "duplicate_work", "unfinished_case"}, r.to_dict()

    g = TokenGraph(p)
    for err in r.errors:
        if err.type == "deadlock":
            m = g.replay(err.path)
            assert not g.enabled_moves(m) and not g.is_complete(m)
        elif err.type == "duplicate_work":
            assert max(g.replay(err.path)) > 1
        elif err.type == "unfinished_case":
            m = g.replay(err.path)
            assert err.path[-1].node == err.nodes[0] and not g.is_complete(m)
