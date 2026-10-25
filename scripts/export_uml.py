"""Export a pathway model as a PlantUML activity diagram (U28–U30, "exported from the editor").

    python scripts/export_uml.py pathways/clinical/triage.json U28 > docs/uml/U28_triage_pathway_activity.puml

Pathways in this platform are block-structured from Start to End, so the export walks the
graph from Start and writes PlantUML's structured blocks: decisions as if/elseif/else,
parallel splits as fork/end fork, task settings as notes (role, deadline, retries,
fallback, undo). Fallback arrows become notes, since PlantUML activity syntax cannot jump.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pathway_core import Edge, Node, Pathway
from pathway_core.settings import deadline, emit, override, retry, undo


class Exporter:
    def __init__(self, p: Pathway) -> None:
        self.p = p
        self.nodes = {n.id: n for n in p.nodes}
        self.lines: list[str] = []

    def out(self, depth: int, text: str) -> None:
        self.lines.append("  " * depth + text)

    def next_of(self, node_id: str) -> list[str]:
        return [e.target for e in self.p.outgoing(node_id) if not e.fallback]

    def walk(self, node_id: str, depth: int, in_branch: bool = False) -> str | None:
        """Write nodes from ``node_id``. Inside a branch, stop at the merge or join that closes it
        and return it; on the main line a merge (e.g. where a fallback rejoins) is passed through."""
        while True:
            n = self.nodes[node_id]
            if n.type in ("xor_merge", "and_join"):
                if in_branch:
                    return node_id
                node_id = self.next_of(node_id)[0]
                continue
            if n.type == "end":
                self.out(depth, f":{self.label(n)};")
                if announced := emit(n):
                    self.out(depth, f"note right: announces **{announced}**")
                self.out(depth, "stop")
                return None
            if n.type in ("xor_split", "and_split"):
                # A block: its branches stop at their merge or join; carry on after it.
                closing = self.decision(n, depth) if n.type == "xor_split" else self.parallel(n, depth)
                if closing is None:  # every branch ended at an End
                    return None
                node_id = self.next_of(closing)[0]
            else:
                self.activity(n, depth)
                node_id = self.next_of(n.id)[0]  # a merge or join here ends this branch (loop top)

    def decision(self, n: Node, depth: int) -> str | None:
        branches = self.p.outgoing(n.id)
        ordered = [e for e in branches if not e.default] + [e for e in branches if e.default]
        merge: str | None = None
        for i, e in enumerate(ordered):
            self.out(depth, self.branch_header(n, e, first=i == 0))
            merge = self.walk(e.target, depth + 1, in_branch=True) or merge
        self.out(depth, "endif")
        return merge

    def branch_header(self, n: Node, e: Edge, first: bool) -> str:
        """``if``/``elseif``/``else`` line of one decision branch, with its probability."""
        probability = f" p={e.prob:g}" if e.prob is not None else ""
        if e.default:
            return f"else (default{probability})"
        guard = e.condition or "true"
        if first:
            return f"if ({self.label(n)}) then ({guard}{probability})"
        return f"elseif () then ({guard}{probability})"

    def parallel(self, n: Node, depth: int) -> str | None:
        join: str | None = None
        for i, target in enumerate(self.next_of(n.id)):
            self.out(depth, "fork" if i == 0 else "fork again")
            join = self.walk(target, depth + 1, in_branch=True) or join
        self.out(depth, "end fork")
        return join

    def activity(self, n: Node, depth: int) -> None:
        if n.type == "start":
            self.out(depth, "start")
            self.out(depth, f":{self.label(n)};")
            if n.trigger:
                self.out(depth, f"note right: started by **{n.trigger}**")
            return
        if n.type == "timer":
            self.out(depth, f":wait {n.minutes:g} min;")
            return
        who = n.role if n.kind == "human" else f"{n.service} ({n.kind})"
        self.out(depth, f":{self.label(n)}\\n<size:10>{who}</size>;")
        notes = self.notes(n)
        if notes:
            self.out(depth, "note right")
            for line in notes:
                self.out(depth + 1, line)
            self.out(depth, "end note")

    @staticmethod
    def notes(n: Node) -> list[str]:
        out = []
        if n.outputs:
            out.append(f"writes {', '.join(n.outputs)}")
        if chain := deadline(n):
            levels = " → ".join(f"{e.role} (+{e.after_min:g} min)" for e in chain.escalation)
            out.append(f"deadline {chain.minutes:g} min" + (f", escalates to {levels}" if levels else ""))
        if policy := retry(n):
            out.append(f"retries {policy.max}× from {policy.base_delay_s:g} s, doubling")
        if n.fallback:
            out.append(f"fails for good → fallback **{n.fallback}**")
        if action := undo(n):
            out.append(f"undo: {action}")
        if check := override(n):
            out.append(f"changing {check.suggested} → {check.decided} needs a reason")
        return out

    @staticmethod
    def label(n: Node) -> str:
        return (n.label or n.id).replace(";", ",")


def export(p: Pathway, diagram_id: str) -> str:
    ex = Exporter(p)
    start = next(n for n in p.nodes if n.type == "start")
    ex.walk(start.id, 0)
    # Fallback targets are not reachable by normal arrows: write each as its own detached lane.
    fallback_targets = sorted({n.fallback for n in p.nodes if n.fallback})
    for target in fallback_targets:
        ex.out(0, "")
        ex.out(0, f'partition "fallback: {ex.label(ex.nodes[target])}" {{')
        ex.activity(ex.nodes[target], 1)
        ex.out(1, f"note right: then continues at {ex.next_of(target)[0]}")
        ex.out(0, "}")
    name = p.name or p.id
    header = [
        f"@startuml {diagram_id}_{p.id}_pathway_activity",
        "!include style.iuml",
        f"title {diagram_id} — {name} v{p.version} (activity, exported from the pathway model)",
    ]
    return "\n".join([*header, *ex.lines, "@enduml", ""])


def main() -> None:
    path, diagram_id = Path(sys.argv[1]), sys.argv[2]
    model: dict[str, Any] = json.loads(path.read_text())
    sys.stdout.write(export(Pathway.from_dict(model), diagram_id))


if __name__ == "__main__":
    main()
