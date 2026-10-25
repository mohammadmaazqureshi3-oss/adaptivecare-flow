"""The message bus: publish-subscribe over one topic exchange, ``care.events``.

``Bus`` is what services depend on. ``InMemoryBus`` gives the same semantics inside one
process (tests and the local dev stack) and can inject faults: every message delivered
twice, or deliveries shuffled. ``care_events.rabbit.RabbitBus`` is the real broker.

Semantics shared by both: each named queue gets a copy of every event whose routing
key matches one of its bindings; delivery is at least once; a handler that raises
gets the message again later (after the consumer has committed nothing).
"""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from care_events.envelope import Event

log = logging.getLogger("care_events.bus")
Handler = Callable[[Event], None]
EXCHANGE = "care.events"


class Bus(Protocol):
    def publish(self, event: Event) -> None: ...

    def subscribe(self, queue_name: str, bindings: list[str], handler: Handler) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


def topic_matches(pattern: str, key: str) -> bool:
    """AMQP topic rules: words split by '.', '*' is exactly one word, '#' is zero or more."""
    return _match(pattern.split("."), key.split("."))


def _match(p: list[str], k: list[str]) -> bool:
    if not p:
        return not k
    if p[0] == "#":
        return any(_match(p[1:], k[i:]) for i in range(len(k) + 1))
    if not k:
        return False
    return (p[0] == "*" or p[0] == k[0]) and _match(p[1:], k[1:])


@dataclass
class _Queue:
    name: str
    bindings: list[str]
    handler: Handler
    items: queue.Queue[tuple[Event, int]] = field(default_factory=queue.Queue)
    busy: bool = False
    thread: threading.Thread | None = None


class InMemoryBus:
    """A broker inside the process. One worker thread per queue, like one consumer per queue."""

    def __init__(
        self,
        *,
        deliver_twice: bool = False,
        shuffle: bool = False,
        max_redeliveries: int = 20,
        seed: int = 0,
    ) -> None:
        self.deliver_twice = deliver_twice
        self.shuffle = shuffle
        self.max_redeliveries = max_redeliveries
        # Test fault injection (shuffling), not security: a seeded generator keeps runs repeatable.
        self.rng = random.Random(seed)  # noqa: S311  # nosec B311
        self.queues: dict[str, _Queue] = {}
        self.published: list[Event] = []
        self.dead_letters: list[tuple[str, Event]] = []
        self._lock = threading.Lock()
        self._running = False

    def subscribe(self, queue_name: str, bindings: list[str], handler: Handler) -> None:
        with self._lock:
            self.queues[queue_name] = _Queue(queue_name, bindings, handler)
            if self._running:
                self._start_queue(self.queues[queue_name])

    def unsubscribe(self, queue_name: str) -> None:
        """Remove a queue (a consumer going away for good, e.g. a retired engine)."""
        with self._lock:
            q = self.queues.pop(queue_name, None)
        if q is not None:
            q.items.put((Event("__stop__"), 0))

    def publish(self, event: Event) -> None:
        with self._lock:
            self.published.append(event)
            targets = [
                q
                for q in self.queues.values()
                if any(topic_matches(b, event.routing_key) for b in q.bindings)
            ]
        copies = 2 if self.deliver_twice else 1
        for q in targets:
            for _ in range(copies):
                q.items.put((event, 0))
            if self.shuffle:
                self._shuffle(q)

    def _shuffle(self, q: _Queue) -> None:
        with q.items.mutex:
            items = list(q.items.queue)
            self.rng.shuffle(items)
            q.items.queue.clear()
            q.items.queue.extend(items)

    def start(self) -> None:
        with self._lock:
            self._running = True
            for q in self.queues.values():
                self._start_queue(q)

    def _start_queue(self, q: _Queue) -> None:
        if q.thread is None:
            q.thread = threading.Thread(target=self._consume, args=(q,), name=f"bus:{q.name}", daemon=True)
            q.thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            queues = list(self.queues.values())
        for q in queues:
            q.items.put((Event("__stop__"), 0))

    def _consume(self, q: _Queue) -> None:
        while True:
            event, tries = q.items.get()
            if event.type == "__stop__":
                return
            q.busy = True
            try:
                q.handler(event)
            except Exception:
                log.exception("handler for %s failed on %s (try %d)", q.name, event.type, tries + 1)
                if tries + 1 >= self.max_redeliveries:
                    self.dead_letters.append((q.name, event))
                else:
                    time.sleep(0.01)
                    q.items.put((event, tries + 1))  # redelivered later, like a nack with requeue
            finally:
                q.busy = False
                q.items.task_done()

    def drain(self, timeout: float = 10.0) -> None:
        """Wait until every queue is empty and idle (tests). Raises TimeoutError otherwise."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(q.items.unfinished_tasks == 0 and not q.busy for q in list(self.queues.values())):
                return
            time.sleep(0.01)
        raise TimeoutError("bus did not drain")
