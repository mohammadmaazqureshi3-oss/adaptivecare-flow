"""The verification report: SAFE, UNSAFE or TOO_LARGE plus each error with its counterexample."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pathway_core import Move

# Error types and the soundness property each one breaks (Section 6 of the plan).
ERROR_TYPES = {
    "structure": "well-formed graph",
    "deadlock": "1. option to complete",
    "cannot_finish": "1. option to complete",
    "unfinished_case": "2. proper completion",
    "dead_step": "3. no dead steps",
    "duplicate_work": "4. safeness",
    "missing_data": "5. data soundness",
    "type_error": "5. data soundness",
    "syntax_error": "5. data soundness",
    "settings": "well-formed task settings",
}


@dataclass
class VerificationError:
    type: str
    nodes: list[str]
    message: str
    path: list[Move] = field(default_factory=list)
    edge: str | None = None  # for condition errors: the branch whose condition is wrong
    pos: int | None = None  # for condition errors: character position

    def key(self) -> tuple[str, tuple[str, ...], str | None, str]:
        # The message is part of the key: two different problems on one node are both reported.
        return (self.type, tuple(sorted(self.nodes)), self.edge, self.message)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "property": ERROR_TYPES[self.type],
            "nodes": self.nodes,
            "message": self.message,
            "path": [
                {"node": mv.node, "consumed": list(mv.consumed), "produced": list(mv.produced)}
                for mv in self.path
            ],
        }
        if self.edge is not None:
            d["edge"] = self.edge
        if self.pos is not None:
            d["pos"] = self.pos
        return d


@dataclass
class Report:
    errors: list[VerificationError] = field(default_factory=list)
    states_explored: int = 0
    too_large: bool = False
    elapsed_ms: float = 0.0

    def add(self, error: VerificationError) -> None:
        self.errors.append(error)

    @property
    def status(self) -> str:
        # A counterexample proves the pathway unsafe even if the search was cut short;
        # TOO_LARGE means the limit was reached before any error was found.
        if self.errors:
            return "UNSAFE"
        return "TOO_LARGE" if self.too_large else "SAFE"

    def deduplicate(self) -> Report:
        """Keep one error per type and node set: the one with the shortest path."""
        best: dict[tuple[str, tuple[str, ...], str | None, str], VerificationError] = {}
        for e in self.errors:
            k = e.key()
            if k not in best or len(e.path) < len(best[k].path):
                best[k] = e
        self.errors = list(best.values())
        return self

    def types(self) -> set[str]:
        return {e.type for e in self.errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [e.to_dict() for e in self.errors],
            "states_explored": self.states_explored,
            "search_complete": not self.too_large,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }
