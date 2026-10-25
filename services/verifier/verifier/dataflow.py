"""Data-flow fixed point: is every variable a step reads set on every path that reaches it?

Starts from "everything set" and shrinks the sets until nothing changes, so the
loop always ends (finitely many variables, sets only shrink). At a parallel
join every branch has run, so the sets are united; anywhere else only one path
is guaranteed, so they are intersected. Union at a join is valid only once the
control flow is known to be sound, which is why this check runs second.
"""

from __future__ import annotations

from pathway_core import Pathway
from pathway_core.conditions import ConditionSyntaxError, names, parse

from verifier.report import VerificationError


def node_reads(p: Pathway, node_id: str) -> set[str]:
    """Variables read by a node: task inputs, plus every name in a decision's conditions."""
    node = p.node(node_id)
    reads = set(node.reads)
    if node.type == "xor_split":
        for e in p.outgoing(node_id):
            if e.condition:
                try:
                    reads |= names(parse(e.condition))
                except ConditionSyntaxError:
                    pass  # reported by the condition check
    return reads


def reverse_postorder(p: Pathway) -> list[str]:
    starts = [n.id for n in p.nodes if n.type == "start"]
    seen: set[str] = set()
    order: list[str] = []

    def visit(nid: str) -> None:
        # Iterative DFS keeps deep pathways clear of Python's recursion limit.
        stack = [(nid, iter(p.outgoing(nid)))]
        seen.add(nid)
        while stack:
            current, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                order.append(current)
            elif nxt.target not in seen:
                seen.add(nxt.target)
                stack.append((nxt.target, iter(p.outgoing(nxt.target))))

    for s in starts:
        visit(s)
    order.reverse()
    # Unreachable nodes are left out: they are dead steps, reported by the state search,
    # and their "everything set" value never wrongly shrinks a reachable node's sets.
    return order


def dataflow_check(p: Pathway) -> list[VerificationError]:
    """Report every reachable step that reads a variable which may be unset."""
    order = reverse_postorder(p)
    inn = available_before(p, order)
    errors = []
    for nid in order:
        missing = node_reads(p, nid) - inn[nid]
        if missing:
            listed = ", ".join(sorted(missing))
            label = p.node(nid).label or nid
            msg = f"Step {label!r} reads {listed}, which may not be set on every path"
            errors.append(VerificationError("missing_data", [nid], msg))
    return errors


def available_before(p: Pathway, order: list[str]) -> dict[str, set[str]]:
    """The fixed point: for each node, the variables set on every path that reaches it."""
    all_vars = {v.name for v in p.variables} | set(p.start_inputs)
    out = {n.id: set(all_vars) for n in p.nodes}
    inn = {n.id: set(all_vars) for n in p.nodes}
    changed = True
    while changed:
        changed = False
        for nid in order:
            node = p.node(nid)
            # A fallback arrow is taken when the task failed, so its outputs are not set.
            arriving = [inn[e.source] if e.fallback else out[e.source] for e in p.incoming(nid)]
            new_in = _combine(node.type, arriving)
            new_out = new_in | set(node.writes)
            if new_in != inn[nid] or new_out != out[nid]:
                inn[nid], out[nid], changed = new_in, new_out, True
    return inn


def _combine(node_type: str, arriving: list[set[str]]) -> set[str]:
    if node_type == "start" or not arriving:
        return set()
    if node_type == "and_join":
        return set().union(*arriving)  # all branches ran
    return set.intersection(*arriving)  # only one path is guaranteed
