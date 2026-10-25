"""Compact pathway builders for verifier tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathway_core import Pathway

PATHWAYS = Path(__file__).resolve().parents[3] / "pathways"


def load(name: str) -> Pathway:
    return Pathway.from_dict(json.loads((PATHWAYS / f"{name}.json").read_text()))


def pw(
    nodes: str,
    edges: str,
    variables: dict[str, str] | None = None,
    **node_settings: dict[str, Any],
) -> Pathway:
    """Build a pathway from text.

    ``nodes``: ``"s:start a:task x:xor_split e:end"``.
    ``edges``: ``"s>a a>x x>e"``; a decision's first branch is the default, later
    branches get the condition ``true`` unless written as ``x>e?cond`` (no spaces).
    """
    node_docs = []
    for item in nodes.split():
        nid, ntype = item.split(":")
        doc: dict[str, Any] = {"id": nid, "type": ntype}
        if ntype == "task":
            doc["kind"] = "human"
            doc["role"] = "nurse"
        doc.update(node_settings.get(nid, {}))
        node_docs.append(doc)
    types = {d["id"]: d["type"] for d in node_docs}
    edge_docs = []
    has_default: set[str] = set()
    for i, item in enumerate(edges.split()):
        arrow, _, cond = item.partition("?")
        a, b = arrow.split(">")
        edoc: dict[str, Any] = {"id": f"{a}>{b}#{i}", "from": a, "to": b}
        if types.get(a) == "xor_split":
            if a not in has_default and not cond:
                edoc["default"] = True
                has_default.add(a)
            else:
                edoc["condition"] = cond or "true"
        edge_docs.append(edoc)
    var_docs = [{"name": k, "type": v} for k, v in (variables or {}).items()]
    return Pathway.from_dict({"id": "test", "variables": var_docs, "nodes": node_docs, "edges": edge_docs})
