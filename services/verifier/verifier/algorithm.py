"""Algorithm 1 — Pathway Verifier.

Decides, before any patient is affected, whether a pathway is sound (van der
Aalst's soundness for workflow nets plus two data checks). If it is not, each
error comes with the shortest sequence of moves that causes it: the search is
breadth-first, so the first path found to any bad state is the shortest one.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from pathway_core import Edge, Marking, Move, Node, Pathway, TokenGraph
from pathway_core.conditions import ConditionSyntaxError, parse, typecheck
from pathway_core.settings import settings_issues

from verifier.dataflow import dataflow_check
from verifier.report import Report, VerificationError

DEFAULT_LIMIT = 200_000
Parent = dict[Marking, tuple[Marking, Move] | None]


def verify(p: Pathway, limit: int = DEFAULT_LIMIT) -> Report:
    t0 = time.perf_counter()
    report = Report()
    fatal = structural_checks(p, report)
    if not fatal:
        g = TokenGraph(p)
        explore(g, report, limit)
        control_flow_sound = not report.errors and not report.too_large
        if control_flow_sound:
            for err in dataflow_check(p):
                report.add(err)
        check_conditions(p, report)
    check_settings(p, report)
    report.deduplicate()
    report.elapsed_ms = (time.perf_counter() - t0) * 1000
    return report


# ---- structural checks (BFS from Start, reverse BFS from End) ---------------


Issue = tuple[list[str], str, bool]  # nodes, message, fatal (the search cannot run)


def structural_checks(p: Pathway, report: Report) -> bool:
    """Add structure errors to ``report``; return True if the graph cannot be searched."""
    for stage in (_reference_issues, _start_end_issues, _shape_issues, _reachability_issues):
        issues = stage(p)
        for nodes, msg, _ in issues:
            report.add(VerificationError("structure", nodes, msg))
        if any(fatal for *_, fatal in issues):
            return True
    return False


def _reference_issues(p: Pathway) -> list[Issue]:
    ids = {n.id for n in p.nodes}
    return [
        ([e.source], f"Arrow {e.id!r} refers to missing step {nid!r}", True)
        for e in p.edges
        for nid in (e.source, e.target)
        if nid not in ids
    ]


def _start_end_issues(p: Pathway) -> list[Issue]:
    starts = [n.id for n in p.nodes if n.type == "start"]
    issues: list[Issue] = []
    if len(starts) != 1:
        issues.append((starts, "A pathway needs exactly one Start", True))
    if not any(n.type == "end" for n in p.nodes):
        issues.append(([], "A pathway needs at least one End", True))
    return issues


def _shape_issues(p: Pathway) -> list[Issue]:
    issues: list[Issue] = []
    for n in p.nodes:
        inc, out = p.incoming(n.id), p.outgoing(n.id)
        if n.type != "start" and not inc:
            issues.append(([n.id], f"Step {n.id!r} has no incoming arrow", False))
        check = _SHAPE_CHECKS.get(n.type)
        if check is not None:
            issues.extend(([n.id], msg, fatal) for msg, fatal in check(n, inc, out))
    return issues


ShapeCheck = Callable[[Node, list[Edge], list[Edge]], list[tuple[str, bool]]]


def _start_shape(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    return ([("Start cannot have incoming arrows", False)] if inc else []) + (
        [("Start needs exactly one outgoing arrow", True)] if len(out) != 1 else []
    )


def _end_shape(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    return [("End cannot have outgoing arrows", False)] if out else []


def _single_out(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    normal = [e for e in out if not e.fallback]
    return [(f"Step {n.id!r} needs exactly one outgoing arrow", False)] if len(normal) != 1 else []


def _join_shape(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    few = [(f"Parallel join {n.id!r} needs at least two incoming arrows", False)] if len(inc) < 2 else []
    return few + _single_out(n, inc, out)


def _split_shape(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    return [(f"Parallel split {n.id!r} needs at least two outgoing arrows", False)] if len(out) < 2 else []


def _decision_shape(n: Node, inc: list[Edge], out: list[Edge]) -> list[tuple[str, bool]]:
    issues = []
    if len(out) < 2:
        issues.append((f"Decision {n.id!r} needs at least two branches", False))
    if sum(e.default for e in out) != 1:
        issues.append((f"Decision {n.id!r} needs exactly one default branch", False))
    issues += [
        (f"Branch {e.id!r} needs a condition or must be the default", False)
        for e in out
        if not e.default and not e.condition
    ]
    return issues


_SHAPE_CHECKS: dict[str, ShapeCheck] = {
    "start": _start_shape,
    "end": _end_shape,
    "task": _single_out,
    "timer": _single_out,
    "xor_merge": _single_out,
    "and_join": _join_shape,
    "and_split": _split_shape,
    "xor_split": _decision_shape,
}


def _reachability_issues(p: Pathway) -> list[Issue]:
    """BFS from Start and reverse BFS from every End."""
    start = next(n.id for n in p.nodes if n.type == "start")
    reach = _bfs(start, lambda nid: [e.target for e in p.outgoing(nid)])
    co_reach = _co_reachable(p)
    issues: list[Issue] = []
    for n in p.nodes:
        if n.id not in reach:
            issues.append(([n.id], f"Step {n.id!r} cannot be reached from Start", False))
        elif n.id not in co_reach:
            issues.append(([n.id], f"No End can be reached from step {n.id!r}", False))
    return issues


def _co_reachable(p: Pathway) -> set[str]:
    found: set[str] = set()
    for end_node in (n for n in p.nodes if n.type == "end"):
        found |= _bfs(end_node.id, lambda nid: [e.source for e in p.incoming(nid)])
    return found


def _bfs(root: str, neighbours: Callable[[str], list[str]]) -> set[str]:
    seen, queue = {root}, deque([root])
    while queue:
        for nxt in neighbours(queue.popleft()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


# ---- state-space exploration ------------------------------------------------


def explore(g: TokenGraph, report: Report, limit: int) -> None:
    """Breadth-first search over every reachable marking.

    A path stops at its first unsafe marking (a token count above one): property
    4 is already broken there, and expanding it further only grows tokens without
    bound inside loops. Such markings count as "settled" for the livelock check,
    and dead steps are not reported when any path was cut, since they could be
    reachable beyond the cut (docs/decisions/0001).
    """
    search = _Search(g, report, limit)
    if search.run():
        search.analyse()


class _Search:
    """State of one exploration: the parent links give the shortest path to each marking."""

    def __init__(self, g: TokenGraph, report: Report, limit: int) -> None:
        self.g, self.report, self.limit = g, report, limit
        m0 = g.initial_marking()
        self.parent: Parent = {m0: None}
        self.queue: deque[Marking] = deque([m0])
        self.succ: dict[Marking, list[Marking]] = {}
        self.fired: set[str] = set()
        self.deadlocks: set[Marking] = set()
        self.unsafe: set[Marking] = set()

    def run(self) -> bool:
        """Explore until done (True) or until the state limit is reached (False)."""
        while self.queue:
            m = self.queue.popleft()
            if max(m, default=0) > 1:
                self.unsafe.add(m)
            elif not self.expand(m):
                self.report.too_large = True
                self.report.states_explored = len(self.parent)
                return False
        self.report.states_explored = len(self.parent)
        return True

    def expand(self, m: Marking) -> bool:
        moves = self.g.successors(m)
        self.succ[m] = [m2 for _, m2 in moves]
        if not moves and not self.g.is_complete(m):
            self.deadlocks.add(m)
            stuck = self.g.nodes_waiting(m)
            msg = f"Deadlock: the case is stuck at {', '.join(stuck)} and is not finished"
            self.report.add(VerificationError("deadlock", stuck, msg, path_to(m, self.parent)))
        for mv, m2 in moves:
            self.fired.add(mv.node)
            check_move(self.g, self.report, m, mv, m2, self.parent)
            if m2 not in self.parent:
                if len(self.parent) >= self.limit:
                    return False
                self.parent[m2] = (m, mv)
                self.queue.append(m2)
        return True

    def analyse(self) -> None:
        settled = {s for s in self.parent if self.g.is_complete(s)} | self.unsafe
        report_livelocks(self.g, self.report, self.parent, self.succ, settled, self.deadlocks)
        if self.unsafe:
            return
        for node in self.g.pathway.nodes:
            if node.type != "start" and node.id not in self.fired:
                msg = f"Dead step: no patient can reach {node.id}"
                self.report.add(VerificationError("dead_step", [node.id], msg))


def check_move(g: TokenGraph, report: Report, m: Marking, mv: Move, m2: Marking, parent: Parent) -> None:
    """Properties 2 and 4, checked on every move as it is generated."""
    if max(m2, default=0) > 1:
        dup = sorted({g.edges[i].target for i, c in enumerate(m2) if c > 1})
        msg = f"Duplicate work: {', '.join(dup)} can run twice for one patient"
        report.add(VerificationError("duplicate_work", dup, msg, path_to(m, parent) + [mv]))
    if g.nodes[mv.node].type == "end" and not g.is_complete(m2):
        msg = f"Unfinished case: {mv.node} fires while {', '.join(g.nodes_waiting(m2))} still have work"
        report.add(VerificationError("unfinished_case", [mv.node], msg, path_to(m, parent) + [mv]))


def report_livelocks(
    g: TokenGraph,
    report: Report,
    parent: Parent,
    succ: dict[Marking, list[Marking]],
    settled: set[Marking],
    deadlocks: set[Marking],
) -> None:
    """Co-reachability: markings from which no completed marking can be reached.

    Only the point of no return is reported (a marking that cannot finish whose
    predecessor still could), and only when no deadlock explains it already.
    """
    can_finish = backward_reachable(succ, settled)
    can_deadlock = backward_reachable(succ, deadlocks)
    for m in set(parent) - can_finish - can_deadlock:
        link = parent[m]
        if link is None or link[0] in can_finish:
            waiting = g.nodes_waiting(m)
            msg = f"Cannot finish: from here the case loops through {', '.join(waiting)} with no way to End"
            report.add(VerificationError("cannot_finish", waiting, msg, path_to(m, parent)))


def backward_reachable(succ: dict[Marking, list[Marking]], targets: set[Marking]) -> set[Marking]:
    """Every marking from which some marking in ``targets`` can be reached."""
    pred: dict[Marking, list[Marking]] = {}
    for m, nexts in succ.items():
        for m2 in nexts:
            pred.setdefault(m2, []).append(m)
    found, queue = set(targets), deque(targets)
    while queue:
        for prev in pred.get(queue.popleft(), []):
            if prev not in found:
                found.add(prev)
                queue.append(prev)
    return found


def path_to(m: Marking, parent: Parent) -> list[Move]:
    path: list[Move] = []
    link = parent[m]
    while link is not None:
        prev, mv = link
        path.append(mv)
        link = parent[prev]
    path.reverse()
    return path


# ---- conditions ---------------------------------------------------------------


def check_conditions(p: Pathway, report: Report) -> None:
    env = p.var_types
    for e in p.edges:
        if not e.condition:
            continue
        try:
            tree = parse(e.condition)
        except ConditionSyntaxError as exc:
            report.add(
                VerificationError(
                    "syntax_error",
                    [e.source],
                    f"Condition {e.condition!r}: {exc.message}",
                    edge=e.id,
                    pos=exc.pos,
                )
            )
            continue
        for issue in typecheck(tree, env):
            report.add(
                VerificationError(
                    "type_error",
                    [e.source],
                    f"Condition {e.condition!r}: {issue.message}",
                    edge=e.id,
                    pos=issue.pos,
                )
            )


# ---- task settings (DES-04) ------------------------------------------------------


def check_settings(p: Pathway, report: Report) -> None:
    """Deadlines, escalation, retries, fallback, undo and durations must be usable as set."""
    nodes = {n.id: n for n in p.nodes}
    for n in p.nodes:
        issues = settings_issues(n)
        if (fb := _fallback_issue(n, nodes)) is not None:
            issues.append(fb)
        for msg in issues:
            report.add(VerificationError("settings", [n.id], f"{n.label or n.id}: {msg}"))


def _fallback_issue(n: Node, nodes: dict[str, Node]) -> str | None:
    if n.fallback is None:
        return None
    if n.type != "task":
        return "only tasks can have a fallback"
    target = nodes.get(n.fallback)
    if n.fallback == n.id or (target is not None and target.type == "start"):
        return "a fallback must lead to another step, not back to itself or to Start"
    return None
