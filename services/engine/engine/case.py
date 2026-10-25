"""Algorithm 2 — the token interpreter for one patient case (plan Section 7).

``Case.apply(event)`` moves the case's tokens with the same eight rules the Verifier
checked and returns the events to send. It is pure and deterministic: no clock, no
I/O, outbound ids and times derived from the inbound event. So replaying a case's stored
inbound events rebuilds exactly the same state and the same outbound events (I3), and a
reply that arrives twice or too late changes nothing (I1).

Failure handling (Sprint 4), in the decision order of Section 7:
* a temporary failure is retried with exponential backoff while retries remain (ENG-07);
* then the fallback branch the designer drew, if any;
* otherwise running branches are cancelled and finished steps with an undo action are
  undone in reverse happened-before order, independent undos in parallel (ENG-08).
Deadlines escalate along the designer's chain, then alert the manager (ENG-06).
Time-based steps ask for a timer (``TimerScheduled``); the engine stores it and later
feeds ``TimerFired`` back through ``apply`` like any other event.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from care_events import Event, derived_id
from pathway_core import Node, Pathway
from pathway_core.conditions import EvaluationError, Expr, evaluate, parse
from pathway_core.settings import deadline, emit, retry, undo

FINAL = frozenset({"completed", "compensated", "failed", "cancelled"})
ACTIVE = frozenset({"running", "compensating"})


@dataclass
class Token:
    id: str
    edge: str | None  # the arrow it sits on, while moving or parked at a join
    node: str | None = None  # the task or timer it waits at
    state: str = "moving"  # moving | parked | waiting | cancelled
    wait: str | None = None  # id of the current wait, e.g. "t0.0@predict#1"; replies must name it
    attempt: int = 1  # attempt number of the current task request (ENG-07)
    level: int = 0  # escalation level of the current task, 0 = the role the designer drew (ENG-06)
    requested_at: int = 0  # event number when the current task was requested (for undo order)


@dataclass
class Step:
    """One line of the case history, in order: what came in or went out, and what it did."""

    direction: str  # in | out
    type: str
    event_id: str
    detail: str
    at: str


@dataclass
class DoneStep:
    """A finished task with an undo action: what compensation would have to reverse."""

    node: str
    requested_at: int
    completed_at: int


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


def undo_levels(done: list[DoneStep]) -> list[list[DoneStep]]:
    """Reverse topological order of happened-before: a step is undone only after every step
    that happened after it. Steps in one level are independent and are undone in parallel.

    x happened before y when x completed no later than the event that requested y: finishing
    a step and requesting the next one happen while handling the same event.
    """
    remaining, levels = list(done), []
    while remaining:
        level = [
            x for x in remaining if not any(x.completed_at <= y.requested_at for y in remaining if y is not x)
        ]
        levels.append(level)
        remaining = [x for x in remaining if x not in level]
    return levels


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
    events: int = 0  # inbound events applied so far
    reason: str = ""
    done: list[DoneStep] = field(default_factory=list)
    undo_plan: list[list[DoneStep]] = field(default_factory=list)  # levels still to undo
    undo_pending: dict[str, str] = field(default_factory=dict)  # undo wait id -> node

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
        self.events += 1
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
            "Compensated": self._compensated,
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

    def _waiting(self, wait: str | None) -> Token | None:
        """The token waiting for exactly this request. A token keeps its id as it moves on, so
        a late reply to an earlier task must not be taken for an answer to its current one."""
        return next((t for t in self.tokens.values() if t.state == "waiting" and t.wait == wait), None)

    def _task_completed(self, e: Event) -> str:
        tok = self._waiting(e.token_id) if self.status == "running" else None
        if tok is None:
            return f"ignored: no task is waiting for {e.token_id} (duplicate or late reply)"
        node = self.nodes[tok.node or ""]
        outputs = e.payload.get("outputs", {})
        bad = [v for v in node.outputs if not type_ok(outputs.get(v), self.var_types.get(v, "string"))]
        if bad:
            return f"rejected: outputs missing or of the wrong type: {', '.join(bad)}"
        self.data.update({v: outputs[v] for v in node.outputs})
        if undo(node):
            self.done.append(DoneStep(node.id, tok.requested_at, self.events))
        self._move_on(tok, self._normal_out(node).id)
        self._advance()
        return f"{node.id} completed with { ({v: outputs[v] for v in node.outputs}) }"

    def _task_failed(self, e: Event) -> str:
        """Section 7's decision order: retry, then fallback, then compensate."""
        tok = self._waiting(e.token_id) if self.status == "running" else None
        if tok is None:
            return f"ignored: no task is waiting for {e.token_id} (duplicate or late reply)"
        node = self.nodes[tok.node or ""]
        reason = str(e.payload.get("reason", "unknown"))
        policy = retry(node)
        if e.payload.get("temporary") and policy and tok.attempt <= policy.max:
            delay = policy.delay(tok.attempt)
            self._schedule("retry", timedelta(seconds=delay), tok, attempt=tok.attempt)
            return f"{node.id} failed ({reason}); retry {tok.attempt} of {policy.max} in {delay:g} s"
        fallback = next((x for x in self.out[node.id] if x.fallback), None)
        if fallback is not None:
            self._move_on(tok, fallback.id)
            self._advance()
            return f"{node.id} failed ({reason}); taking the fallback to {fallback.target}"
        tok.state = "cancelled"  # it already failed: no CancelRequested for it
        return self._compensate(f"{node.id} failed ({reason}) and has no fallback")

    def _timer(self, e: Event) -> str:
        kind = e.payload.get("kind")
        tok = self._waiting(e.payload.get("wait")) if self.status == "running" else None
        if tok is None:
            return f"ignored: {kind} timer for {e.payload.get('wait')}, which no longer waits"
        node = self.nodes[tok.node or ""]
        if kind == "timer" and node.type == "timer":
            self._move_on(tok, self._normal_out(node).id)
            self._advance()
            return f"timer {node.id} fired"
        if kind == "retry" and e.payload.get("attempt") == tok.attempt:
            tok.attempt += 1
            self._request(tok, node)
            return f"{node.id}: attempt {tok.attempt} requested"
        if kind == "deadline" and e.payload.get("level") == tok.level:
            return self._escalate(tok, node)
        return f"ignored: stale {kind} timer for {node.id}"

    # ---- deadlines and escalation (ENG-06) -------------------------------------------

    def _escalate(self, tok: Token, node: Node) -> str:
        chain = deadline(node)
        steps = chain.escalation if chain else ()
        label, patient = node.label or node.id, self.data.get("patient_id")
        if tok.level < len(steps):
            esc = steps[tok.level]
            tok.level += 1
            due = self._at(timedelta(minutes=esc.after_min))
            self._send(
                "TaskReassigned", {"task_id": tok.wait, "role": esc.role, "level": tok.level, "due_at": due}
            )
            message = f"Overdue: '{label}' for {patient} is now yours (escalation level {tok.level})"
            self._send("NotificationRequested", {"role": esc.role, "message": message, "case_id": self.id})
            self._schedule("deadline", timedelta(minutes=esc.after_min), tok, level=tok.level)
            return f"{node.id} overdue: reassigned to {esc.role}"
        message = f"'{label}' for {patient} is still open after every escalation level"
        self._send("NotificationRequested", {"role": "manager", "message": message, "case_id": self.id})
        return f"{node.id} overdue after the whole chain: manager alerted"

    # ---- compensation (ENG-08) --------------------------------------------------------

    def _compensate(self, reason: str) -> str:
        """Cancel running branches, then undo finished steps level by level."""
        self.reason = reason
        for tok in self.tokens.values():
            if tok.state == "waiting" and tok.node and self.nodes[tok.node].type == "task":
                node = self.nodes[tok.node]
                target = "worklist" if node.kind == "human" else str(node.service)
                self._send(
                    "CancelRequested",
                    {"task_id": tok.wait, "node": node.id},
                    token_id=tok.wait,
                    target=target,
                )
            tok.state = "cancelled"
        if not self.done:
            return self._fail(reason)
        self.status = "compensating"
        self.undo_plan = undo_levels(self.done)
        self._next_undo_level()
        return f"{reason}: compensating {len(self.done)} finished step(s)"

    def _next_undo_level(self) -> None:
        if not self.undo_plan:
            self.status = "compensated"
            self._send("CaseCompensated", {"reason": self.reason})
            return
        for step in self.undo_plan.pop(0):
            node = self.nodes[step.node]
            self.waits += 1
            wait = f"undo:{node.id}#{self.waits}"
            self.undo_pending[wait] = node.id
            target = "worklist" if node.kind == "human" else str(node.service)
            payload: dict[str, Any] = {
                "task_id": wait,
                "node": node.id,
                "action": undo(node),
                "label": f"Undo: {node.label or node.id}",
                "role": node.role,
                "patient_id": self.data.get("patient_id"),
                "outputs": [],
                "inputs": {},
            }
            self._send("CompensateRequested", payload, token_id=wait, target=target)

    def _compensated(self, e: Event) -> str:
        node = self.undo_pending.pop(e.token_id or "", None) if self.status == "compensating" else None
        if node is None:
            return f"ignored: no undo is waiting for {e.token_id}"
        if e.payload.get("ok", True) is False:
            self._send(
                "NotificationRequested",
                {
                    "role": "manager",
                    "message": f"Undo of {node} failed; case needs attention",
                    "case_id": self.id,
                },
            )
            return self._fail(f"{self.reason}; undo of {node} failed")
        if not self.undo_pending:
            self._next_undo_level()
        return f"{node} undone"

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

    def _move_on(self, tok: Token, edge: str) -> None:
        tok.edge, tok.node, tok.state, tok.wait = edge, None, "moving", None
        tok.attempt, tok.level = 1, 0

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
        tok.wait, tok.requested_at = f"{tok.id}@{node.id}#{self.waits}", self.events
        if node.type == "timer":
            self._schedule("timer", timedelta(minutes=node.minutes or 0), tok)
            return
        chain = deadline(node)
        if chain:
            self._schedule("deadline", timedelta(minutes=chain.minutes), tok, level=0)
        self._request(tok, node)

    def _end(self, tok: Token, node: Node) -> None:
        """Rule 8: End takes the token; the case is complete when none is left.
        An End may announce an event that starts another pathway (e.g. TriageCompleted)."""
        del self.tokens[tok.id]
        if not any(t.state != "cancelled" for t in self.tokens.values()):
            self.status = "completed"
            self._send("CaseCompleted", {"data": self.data, "end": node.id})
            if announced := emit(node):
                self._send(announced, {**self.data, "from_case": self.id, "from_pathway": self.pathway.id})

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

    def _at(self, delay: timedelta) -> str:
        """A time relative to the inbound event, so replay computes the same due times."""
        cause = self._cause
        if cause is None:
            raise RuntimeError("no current event")
        return (datetime.fromisoformat(cause.timestamp) + delay).isoformat()

    def _schedule(self, kind: str, delay: timedelta, tok: Token, **extra: Any) -> None:
        payload = {"kind": kind, "wait": tok.wait, "due_at": self._at(delay), **extra}
        self._send("TimerScheduled", payload, token_id=tok.wait)

    def _request(self, tok: Token, node: Node) -> None:
        target = "worklist" if node.kind == "human" else str(node.service)
        chain = deadline(node)
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
            "override": node.settings.get("override"),  # WRK-02: a change needs a reason
            "due_at": self._at(timedelta(minutes=chain.minutes)) if chain else None,
            "patient_id": self.data.get("patient_id"),
        }
        self._send("TaskRequested", payload, token_id=tok.wait, target=target, attempt=tok.attempt)

    def _fail(self, reason: str) -> str:
        self.status, self.reason = "failed", reason
        for tok in self.tokens.values():
            tok.state = "cancelled"
        self._send("CaseFailed", {"reason": reason})
        return f"case failed: {reason}"

    def _send(
        self,
        type: str,
        payload: dict[str, Any],
        *,
        token_id: str | None = None,
        target: str | None = None,
        attempt: int = 1,
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
            attempt=attempt,
            timestamp=cause.timestamp,
            target=target,
        )
        self._sent.append(event)
        detail = f"to {target}" if target else ""
        self.history.append(Step("out", type, event.event_id, detail, cause.timestamp))

    # ---- views and snapshots (ENG-09) -------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Everything that defines the case; two cases with equal states are the same (I3)."""
        return {
            "id": self.id,
            "status": self.status,
            "reason": self.reason,
            "data": dict(sorted(self.data.items())),
            "tokens": {
                t.id: (t.edge, t.node, t.state, t.wait, t.attempt, t.level)
                for t in sorted(self.tokens.values(), key=lambda t: t.id)
            },
            "joins_fired": dict(sorted(self.joins_fired.items())),
            "undo_pending": dict(sorted(self.undo_pending.items())),
        }

    def snapshot(self) -> dict[str, Any]:
        """Everything needed to continue the case without replaying its earlier events."""
        return {
            "status": self.status,
            "data": self.data,
            "tokens": [asdict(t) for t in self.tokens.values()],
            "history": [asdict(h) for h in self.history],
            "joins_fired": self.joins_fired,
            "waits": self.waits,
            "events": self.events,
            "reason": self.reason,
            "done": [asdict(d) for d in self.done],
            "undo_plan": [[asdict(d) for d in level] for level in self.undo_plan],
            "undo_pending": self.undo_pending,
        }

    @classmethod
    def from_snapshot(cls, pathway: Pathway, case_id: str, snap: dict[str, Any]) -> Case:
        case = cls(pathway, case_id)
        case.status, case.data, case.reason = snap["status"], snap["data"], snap["reason"]
        case.tokens = {t["id"]: Token(**t) for t in snap["tokens"]}
        case.history = [Step(**h) for h in snap["history"]]
        case.joins_fired, case.waits, case.events = snap["joins_fired"], snap["waits"], snap["events"]
        case.done = [DoneStep(**d) for d in snap["done"]]
        case.undo_plan = [[DoneStep(**d) for d in level] for level in snap["undo_plan"]]
        case.undo_pending = snap["undo_pending"]
        return case
