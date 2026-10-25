"""The eight token rules: the one definition of what a pathway means.

A token sits on an arrow. A marking records how many tokens sit on each arrow;
it is the state of a case. Markings are immutable tuples indexed by edge
position, so they can be stored in sets and compared in constant time.

The Verifier uses ``enabled_moves`` to explore every possible move, the Engine
and Simulator use the same rules with live or sampled data choosing the branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from pathway_core.model import Edge, Node, Pathway

Marking = tuple[int, ...]


@dataclass(frozen=True)
class Move:
    """One firing of one node: tokens taken from ``consumed``, put on ``produced``."""

    node: str
    consumed: tuple[str, ...]
    produced: tuple[str, ...]


class TokenGraph:
    """A pathway indexed for fast token moves (edge ids to positions)."""

    def __init__(self, pathway: Pathway) -> None:
        self.pathway = pathway
        self.edges: tuple[Edge, ...] = pathway.edges
        self.index = {e.id: i for i, e in enumerate(self.edges)}
        self.inc: dict[str, list[int]] = {n.id: [] for n in pathway.nodes}
        self.out: dict[str, list[int]] = {n.id: [] for n in pathway.nodes}
        for i, e in enumerate(self.edges):
            if e.target in self.inc:
                self.inc[e.target].append(i)
            if e.source in self.out:
                self.out[e.source].append(i)
        self.nodes: dict[str, Node] = {n.id: n for n in pathway.nodes}

    @cached_property
    def starts(self) -> list[Node]:
        return [n for n in self.pathway.nodes if n.type == "start"]

    # ---- markings ----------------------------------------------------------

    def empty(self) -> Marking:
        return (0,) * len(self.edges)

    def initial_marking(self) -> Marking:
        """Rule 1: Start puts one token on its outgoing arrow."""
        m = list(self.empty())
        for start in self.starts:
            for i in self.out[start.id]:
                m[i] += 1
        return tuple(m)

    @staticmethod
    def is_complete(m: Marking) -> bool:
        """Rule 8: a case is complete when no token is left anywhere."""
        return not any(m)

    def marked_edges(self, m: Marking) -> list[str]:
        return [self.edges[i].id for i, c in enumerate(m) if c]

    # ---- moves -------------------------------------------------------------

    def enabled_moves(self, m: Marking) -> list[Move]:
        """Every move allowed in marking ``m``; a decision gives one move per branch."""
        moves: list[Move] = []
        for node in self.pathway.nodes:
            if node.type == "start":
                continue
            inc = self.inc[node.id]
            if node.type == "and_join":
                # Rule 6: fires only when every incoming arrow holds a token.
                if inc and all(m[i] for i in inc):
                    moves.extend(self._outputs(node, tuple(inc)))
                continue
            # Rules 2, 3, 4, 5, 7, 8: take one token from any marked incoming arrow.
            for i in inc:
                if m[i]:
                    moves.extend(self._outputs(node, (i,)))
        return moves

    def _outputs(self, node: Node, consumed: tuple[int, ...]) -> list[Move]:
        taken = tuple(self.edges[i].id for i in consumed)
        out = [self.edges[i] for i in self.out[node.id]]
        if node.type == "end":
            return [Move(node.id, taken, ())]
        if node.type == "xor_split":
            # Rule 3: exactly one outgoing arrow.
            return [Move(node.id, taken, (e.id,)) for e in out]
        if node.type == "and_split":
            # Rule 5: every outgoing arrow.
            return [Move(node.id, taken, tuple(e.id for e in out))]
        return self._single_step(node, taken, out)

    @staticmethod
    def _single_step(node: Node, taken: tuple[str, ...], out: list[Edge]) -> list[Move]:
        """Rules 2, 4, 6, 7: one token onward; a task that fails for good takes its fallback."""
        normal = tuple(e.id for e in out if not e.fallback)
        return [Move(node.id, taken, normal)] + [Move(node.id, taken, (e.id,)) for e in out if e.fallback]

    def fire(self, m: Marking, move: Move) -> Marking:
        """Apply ``move`` to ``m``. Raises ``ValueError`` if it is not enabled."""
        new = list(m)
        for eid in move.consumed:
            i = self.index[eid]
            if new[i] < 1:
                raise ValueError(f"move {move} is not enabled: no token on {eid}")
            new[i] -= 1
        for eid in move.produced:
            new[self.index[eid]] += 1
        return tuple(new)

    def successors(self, m: Marking) -> list[tuple[Move, Marking]]:
        return [(mv, self.fire(m, mv)) for mv in self.enabled_moves(m)]

    def nodes_waiting(self, m: Marking) -> list[str]:
        """Nodes that have a token on at least one incoming arrow."""
        return sorted({self.edges[i].target for i, c in enumerate(m) if c})

    def replay(self, path: list[Move]) -> Marking:
        """Fire ``path`` from the initial marking; used to check counterexamples."""
        m = self.initial_marking()
        for mv in path:
            m = self.fire(m, mv)
        return m
