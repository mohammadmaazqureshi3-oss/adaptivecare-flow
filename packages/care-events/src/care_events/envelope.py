"""The event envelope every service sends and receives (contracts/events.md).

Ids are UUIDs. Events a service derives from another event get *deterministic* ids
(``derived_id``), so processing the same input twice produces the same output ids
and consumers can drop the copy (invariant I1).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

NAMESPACE = uuid.UUID("6f0f6c8e-2a51-4f0e-9a67-6d1b7c3e5a10")

# Replies go back to the engine that asked: their routing key names its pathway version.
REPLY_TYPES = frozenset({"TaskCompleted", "TaskFailed", "Compensated", "TimerFired"})
# Requests go to one kind of worker: their routing key names the target service.
REQUEST_TYPES = frozenset({"TaskRequested", "CompensateRequested", "CancelRequested"})


def derived_id(*parts: object) -> str:
    """A stable UUID for an event caused by ``parts`` (e.g. case id, cause event id, position)."""
    return str(uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str | None = None
    token_id: str | None = None
    pathway: str | None = None
    version: int | None = None
    attempt: int = 1
    timestamp: str = field(default_factory=utc_now)
    target: str | None = None  # the service a request is for (TaskRequested.<target>)

    @property
    def routing_key(self) -> str:
        if self.type in REPLY_TYPES:
            return f"{self.type}.{self.pathway}.v{self.version}"
        if self.type in REQUEST_TYPES:
            return f"{self.type}.{self.target}"
        return self.type

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str | bytes) -> Event:
        return cls(**json.loads(text))

    def reply(self, type: str, payload: dict[str, Any], *, position: int = 0) -> Event:
        """The answer to a request, addressed to the engine that sent it, with a stable id."""
        return Event(
            type=type,
            payload=payload,
            event_id=derived_id(self.event_id, type, position),
            case_id=self.case_id,
            token_id=self.token_id,
            pathway=self.pathway,
            version=self.version,
            attempt=self.attempt,
        )
