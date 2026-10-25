"""The pathway model: the JSON graph that the editor saves and every algorithm reads.

A pathway is a directed graph of nodes joined by edges (arrows). Its meaning is
fixed by the token rules in ``pathway_core.tokens``. This module only parses,
normalises and serialises the model; it never decides anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NODE_TYPES = frozenset({"start", "task", "xor_split", "xor_merge", "and_split", "and_join", "timer", "end"})
TASK_KINDS = frozenset({"human", "service", "ml"})
VAR_TYPES = frozenset({"int", "float", "bool", "string"})


class ModelError(ValueError):
    """Raised when a pathway JSON document cannot be turned into a model."""


@dataclass(frozen=True)
class Variable:
    name: str
    type: str


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    label: str = ""
    kind: str | None = None  # task only: human, service or ml
    role: str | None = None  # human tasks
    service: str | None = None  # service and ml tasks
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    trigger: str | None = None  # start only
    minutes: float | None = None  # timer only
    fallback: str | None = None  # node id taken when the task fails for good
    settings: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def reads(self) -> frozenset[str]:
        # A Start node's inputs arrive with its trigger event: it writes them.
        return frozenset() if self.type == "start" else frozenset(self.inputs)

    @property
    def writes(self) -> frozenset[str]:
        return frozenset(self.inputs) if self.type == "start" else frozenset(self.outputs)


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    condition: str | None = None  # xor_split branches only
    default: bool = False  # the xor_split branch taken when no condition holds
    prob: float | None = None  # used by the Simulator when it cannot evaluate
    fallback: bool = False  # synthetic edge from a task to its fallback node


@dataclass(frozen=True)
class Pathway:
    id: str
    version: int
    variables: tuple[Variable, ...]
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    name: str = ""

    # ---- lookups -----------------------------------------------------------

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def outgoing(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    @property
    def var_types(self) -> dict[str, str]:
        return {v.name: v.type for v in self.variables}

    @property
    def start_inputs(self) -> frozenset[str]:
        return frozenset(i for n in self.nodes if n.type == "start" for i in n.inputs)

    # ---- (de)serialisation -------------------------------------------------

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Pathway:
        try:
            variables = tuple(Variable(v["name"], v["type"]) for v in doc.get("variables", []))
            nodes = tuple(_node_from_dict(n) for n in doc["nodes"])
            edges = [_edge_from_dict(e, i) for i, e in enumerate(doc["edges"])]
        except KeyError as exc:
            raise ModelError(f"missing field {exc}") from exc

        # A task's fallback is stored on the node but behaves like an arrow, so
        # every algorithm sees it as one extra outgoing edge marked ``fallback``.
        edges += [Edge(f"{n.id}~>{n.fallback}", n.id, n.fallback, fallback=True) for n in nodes if n.fallback]
        _validate(variables, nodes, edges)

        return cls(
            id=str(doc["id"]),
            version=int(doc.get("version", 1)),
            name=str(doc.get("name", "")),
            variables=variables,
            nodes=nodes,
            edges=tuple(edges),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "variables": [{"name": v.name, "type": v.type} for v in self.variables],
            "nodes": [_node_to_dict(n) for n in self.nodes],
            "edges": [_edge_to_dict(e) for e in self.edges if not e.fallback],
        }


def _validate(variables: tuple[Variable, ...], nodes: tuple[Node, ...], edges: list[Edge]) -> None:
    for v in variables:
        if v.type not in VAR_TYPES:
            raise ModelError(f"variable {v.name!r} has unknown type {v.type!r}")
    if len({e.id for e in edges}) != len(edges):
        raise ModelError("duplicate edge ids")
    if len({n.id for n in nodes}) != len(nodes):
        raise ModelError("duplicate node ids")


_NODE_FIELDS = ("label", "kind", "role", "service", "trigger", "minutes", "fallback")


def _node_from_dict(d: dict[str, Any]) -> Node:
    node_type = d["type"]
    if node_type not in NODE_TYPES:
        raise ModelError(f"node {d.get('id')!r} has unknown type {node_type!r}")
    kind = d.get("kind")
    if node_type == "task" and kind not in TASK_KINDS:
        raise ModelError(f"task {d['id']!r} needs kind human, service or ml")
    known = {"id", "type", "inputs", "outputs", *_NODE_FIELDS}
    return Node(
        id=str(d["id"]),
        type=node_type,
        label=str(d.get("label", "")),
        kind=kind,
        role=d.get("role"),
        service=d.get("service"),
        inputs=tuple(d.get("inputs", ())),
        outputs=tuple(d.get("outputs", ())),
        trigger=d.get("trigger"),
        minutes=d.get("minutes"),
        fallback=d.get("fallback"),
        settings={k: v for k, v in d.items() if k not in known},
    )


def _node_to_dict(n: Node) -> dict[str, Any]:
    d: dict[str, Any] = {"id": n.id, "type": n.type}
    for name in _NODE_FIELDS:
        value = getattr(n, name)
        if value not in (None, ""):
            d[name] = value
    if n.inputs:
        d["inputs"] = list(n.inputs)
    if n.outputs:
        d["outputs"] = list(n.outputs)
    d.update(n.settings)
    return d


def _edge_from_dict(d: dict[str, Any], index: int) -> Edge:
    source, target = str(d["from"]), str(d["to"])
    return Edge(
        id=str(d.get("id") or f"{source}->{target}#{index}"),
        source=source,
        target=target,
        condition=d.get("condition"),
        default=bool(d.get("default", False)),
        prob=d.get("prob"),
    )


def _edge_to_dict(e: Edge) -> dict[str, Any]:
    d: dict[str, Any] = {"id": e.id, "from": e.source, "to": e.target}
    if e.condition is not None:
        d["condition"] = e.condition
    if e.default:
        d["default"] = True
    if e.prob is not None:
        d["prob"] = e.prob
    return d
