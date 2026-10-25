"""Algorithm 2 — the token interpreter for one patient case (plan Section 7).

``Case.apply(event)`` moves the case's tokens with the same eight rules the Verifier
checked and returns the events to send. It is pure and deterministic: no clock, no
I/O, outbound ids derived from the inbound event. So replaying a case's stored inbound
events rebuilds exactly the same state and the same outbound events (invariant I3),
and a reply that arrives twice or too late changes nothing (I1).

Sprint 3 scope: start, tasks, decisions on live data, parallel split and join, end, a
fallback branch on permanent failure. Retries with backoff, deadlines and escalation,
compensation and timers' scheduling arrive in Sprint 4 (ENG-06..09).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from care_events import Event, derived_id
from pathway_core import Node, Pathway
from pathway_core.conditions import EvaluationError, Expr, evaluate, parse

FINAL = frozenset({"completed", "compensated", "failed", "cancelled"})


@dataclass
class Token:
    id: str
    edge: str | None  # the arrow it sits on, while moving or parked at a join
    node: str | None = None  # the task or timer it waits at
    state: str = "moving"  # moving | parked | waiting | cancelled
    wait: str | None = None  # id of the current wait, e.g. "t0.0@predict#1"; replies must name it


@dataclass
class Step:
    """One line of the case history, in order: what came in or went out, and what it did."""

    direction: str  # in | out
    type: str
    event_id: str
    detail: str
    at: str


def type_ok(value: Any, var_type: str) -> bool:
    if var_type == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if var_type == "int":
        return isinstance(value, int)
    if var_type == "float":
        return isinstance(value, int | float)
    return isinstance(value, str)


@dataclass
class Case:
    pathway: Pathway
    id: str
    status: str = "new"
    data: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, Token] = field(default_factory=dict)
    history: list[Step] = field(default_factory=list)
    joins_fired: dict[str, int] = field(default_factory=dict)
    waits: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        p = self.pathway
        self.nodes: dict[str, Node] = {n.id: n for n in p.nodes}
        self.edges = {e.id: e for e in p.edges}
        self.out = {n.id: [e for e in p.outgoing(n.id)] for n in p.nodes}
        self.inc = {n.id: [e.id for e in p.incoming(n.id)] for n in p.nodes}
        self.var_types = p.var_types
        self.conditions: dict[str, Expr] = {e.id: parse(e.condition) for e in p.edges if e.condition}
        self._cause: Event | None = None
        self._sent: list[Event] = []

    # ---- entry point ---------------------------------------------------------------

    def apply(self, event: Event) -> list[Event]:
        """Handle one inbound event; return the events to publish (possibly none)."""
        self._cause, self._sent = event, []
        step = Step("in", event.type, event.event_id, "", event.timestamp)
        self.history.append(step)  # before the events it causes, so the history reads in order
        step.detail = self._dispatch(event)
        return self._sent

    def _dispatch(self, e: Event) -> str:
        if self.status in FINAL:
            return f"ignored: the case is already {self.status} (late message)"
        if self.trigger is not None and e.type == self.trigger:
            return self._start(e)
        if self.status == "new":
            return "ignored: the case has not started"
        handlers = {
            "TaskCompleted": self._task_completed,
            "TaskFailed": self._task_failed,
            "TimerFired": self._timer,
        }
        handler = handlers.get(e.type)
        return handler(e) if handler else f"ignored: {e.type} is not handled by the engine"

    @property
    def trigger(self) -> str | None:
        """The event that starts a case; None means no event starts one automatically."""
        start = next(n for n in self.pathway.nodes if n.type == "start")
        return start.trigger or None

    # ---- inbound events ------------------------------------------------------------

    def _start(self, e: Event) -> str:
        if self.status != "new":
            return "ignored: the case has already started"
        start = next(n for n in self.pathway.nodes if n.type == "start")
        missing = [v for v in start.inputs if not type_ok(e.payload.get(v), self.var_types.get(v, "string"))]
        self.status = "running"
        self._send("CaseStarted", {"patient_id": e.payload.get("patient_id"), "trigger": e.type})
        if missing:
            return self._fail(f"start inputs missing or of the wrong type: {', '.join(missing)}")
        self.data = {v: e.payload[v] for v in start.inputs}
        self.tokens["t0"] = Token("t0", self.out[start.id][0].id)
        self._advance()
        return f"case started with {self.data}"

    def _waiting(self, e: Event) -> Token | None:
        """The token waiting for exactly this request. A token keeps its id as it moves on, so
        a late reply to an earlier task must not be taken for an answer to its current one."""
        return next((t for t in self.tokens.values() if t.state == "waiting" and t.wait == e.token_id), None)

    def _task_completed(self, e: Event) -> str:
        tok = self._waiting(e)
        if tok is None:
            return f"ignored: no task is waiting for {e.token_id} (duplicate or late reply)"
        node = self.nodes[tok.node or ""]
        outputs = e.payload.get("outputs", {})
        bad = [v for v in node.outputs if not type_ok(outputs.get(v), self.var_types.get(v, "string"))]
        if bad:
            return f"rejected: outputs missing or of the wrong type: {', '.join(bad)}"
        self.data.update({v: outputs[v] for v in node.outputs})
        tok.edge, tok.node, tok.state, tok.wait = self._normal_out(node).id, None, "moving", None
        self._advance()
        return f"{node.id} completed with { ({v: outputs[v] for v in node.outputs}) }"

    def _task_failed(self, e: Event) -> str:
        tok = self._waiting(e)
        if tok is None:
            return f"ignored: no task is waiting for {e.token_id} (duplicate or late reply)"
        node = self.nodes[tok.node or ""]
        reason = str(e.payload.get("reason", "unknown"))
        fallback = next((x for x in self.out[node.id] if x.fallback), None)
        if fallback is not None:
            tok.edge, tok.node, tok.state, tok.wait = fallback.id, None, "moving", None
            self._advance()
            return f"{node.id} failed ({reason}); taking the fallback to {fallback.target}"
        return self._fail(f"{node.id} failed ({reason}) and has no fallback")

    def _timer(self, e: Event) -> str:
        tok = self._waiting(e)
        if tok is None or self.nodes[tok.node or ""].type != "timer":
            return f"ignored: no timer is waiting for token {e.token_id}"
        node = self.nodes[tok.node or ""]
        tok.edge, tok.node, tok.state, tok.wait = self._normal_out(node).id, None, "moving", None
        self._advance()
        return f"timer {node.id} fired"

    # ---- the token rules -----------------------------------------------------------

    def _advance(self) -> None:
        """Move every movable token until each one waits, parks, or the case ends."""
        while self.status == "running":
            movable = sorted(t for t, tok in self.tokens.items() if tok.state == "moving")
            if not movable:
                return
            self._step(self.tokens[movable[0]])

    def _step(self, tok: Token) -> None:
        node = self.nodes[self.edges[tok.edge or ""].target]
        handler = {
            "xor_split": self._decide,
            "xor_merge": self._merge,
            "and_split": self._split,
            "and_join": self._join,
            "task": self._wait,
            "timer": self._wait,
            "end": self._end,
        }[node.type]
        handler(tok, node)

    def _merge(self, tok: Token, node: Node) -> None:
        """Rule 4: pass each arriving token on."""
        tok.edge = self.out[node.id][0].id

    def _split(self, tok: Token, node: Node) -> None:
        """Rule 5: one token in, one token out on every outgoing arrow."""
        del self.tokens[tok.id]
        for k, edge in enumerate(self.out[node.id]):
            child = f"{tok.id}.{k}"
            self.tokens[child] = Token(child, edge.id)

    def _wait(self, tok: Token, node: Node) -> None:
        """Rules 2 and 7: the token waits at the task or timer until its reply comes."""
        self.waits += 1
        tok.edge, tok.node, tok.state = None, node.id, "waiting"
        tok.wait = f"{tok.id}@{node.id}#{self.waits}"
        self._request(tok, node)

    def _end(self, tok: Token, node: Node) -> None:
        """Rule 8: End takes the token; the case is complete when none is left."""
        del self.tokens[tok.id]
        if not any(t.state != "cancelled" for t in self.tokens.values()):
            self.status = "completed"
            self._send("CaseCompleted", {"data": self.data})

    def _decide(self, tok: Token, node: Node) -> None:
        """Rule 3: the first branch whose condition holds, otherwise the default."""
        branches = self.out[node.id]
        try:
            chosen = next(
                (b for b in branches if not b.default and evaluate(self.conditions[b.id], self.data)), None
            )
        except EvaluationError as exc:
            self._fail(f"decision {node.id} could not be evaluated: {exc}")
            return
        tok.edge = (chosen or next(b for b in branches if b.default)).id

    def _join(self, tok: Token, node: Node) -> None:
        """Rule 6: fire once every incoming arrow holds a token; otherwise park (I2)."""
        tok.state = "parked"
        waiting = {
            edge: [t for t in self.tokens.values() if t.edge == edge and t.state == "parked"]
            for edge in self.inc[node.id]
        }
        if not all(waiting.values()):
            return
        for tokens_on_edge in waiting.values():
            del self.tokens[sorted(tokens_on_edge, key=lambda t: t.id)[0].id]
        n = self.joins_fired.get(node.id, 0) + 1
        self.joins_fired[node.id] = n
        new_id = f"{node.id}@{n}"
        self.tokens[new_id] = Token(new_id, self.out[node.id][0].id)

    def _normal_out(self, node: Node) -> Any:
        return next(x for x in self.out[node.id] if not x.fallback)

    # ---- outbound events -------------------------------------------------------------

    def _request(self, tok: Token, node: Node) -> None:
        if node.type == "timer":
            self._send("TimerRequested", {"node": node.id, "minutes": node.minutes}, token_id=tok.wait)
            return
        target = "worklist" if node.kind == "human" else str(node.service)
        payload = {
            "task_id": tok.wait,
            "node": node.id,
            "label": node.label or node.id,
            "kind": node.kind,
            "role": node.role,
            "service": node.service,
            "inputs": {v: self.data.get(v) for v in node.inputs},
            "outputs": [{"name": v, "type": self.var_types.get(v, "string")} for v in node.outputs],
            "deadline": node.settings.get("deadline"),
            "patient_id": self.data.get("patient_id"),
        }
        self._send("TaskRequested", payload, token_id=tok.wait, target=target)

    def _fail(self, reason: str) -> str:
        self.status, self.reason = "failed", reason
        for tok in self.tokens.values():
            tok.state = "cancelled"
        self._send("CaseFailed", {"reason": reason})
        return f"case failed: {reason}"

    def _send(
        self, type: str, payload: dict[str, Any], *, token_id: str | None = None, target: str | None = None
    ) -> None:
        cause = self._cause
        if cause is None:
            raise RuntimeError("_send called outside apply()")
        event = Event(
            type=type,
            payload=payload,
            event_id=derived_id(self.id, cause.event_id, len(self._sent)),
            case_id=self.id,
            token_id=token_id,
            pathway=self.pathway.id,
            version=self.pathway.version,
            timestamp=cause.timestamp,
            target=target,
        )
        self._sent.append(event)
        detail = f"to {target}" if target else ""
        self.history.append(Step("out", type, event.event_id, detail, cause.timestamp))

    # ---- views -----------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Everything that defines the case; two cases with equal states are the same (I3)."""
        return {
            "id": self.id,
            "status": self.status,
            "reason": self.reason,
            "data": dict(sorted(self.data.items())),
            "tokens": {
                t.id: (t.edge, t.node, t.state, t.wait)
                for t in sorted(self.tokens.values(), key=lambda t: t.id)
            },
            "joins_fired": dict(sorted(self.joins_fired.items())),
        }
