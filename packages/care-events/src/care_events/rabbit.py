"""RabbitMQ implementation of ``Bus`` (used in Docker Compose).

One durable topic exchange ``care.events``; one durable queue per consumer, bound by
routing-key patterns; persistent messages; manual acknowledgement after the handler
returns (so a crash before commit means redelivery, never loss); prefetch 1.

pika connections are not thread-safe, so publishing uses its own connection behind a
lock, and each consumer queue gets a thread with its own connection.

Status: written against the pika 1.4 API; not yet run against a live broker (Docker was
unavailable during Sprint 3). The in-memory bus has the same semantics and carries the
tests; the Compose integration test in Sprint 3's plan runs this class.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel

from care_events.bus import EXCHANGE, Handler
from care_events.envelope import Event

log = logging.getLogger("care_events.rabbit")


class RabbitBus:
    def __init__(self, url: str, reconnect_delay_s: float = 2.0) -> None:
        self.params = pika.URLParameters(url)
        self.reconnect_delay_s = reconnect_delay_s
        self._subs: list[tuple[str, list[str], Handler]] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._pub_lock = threading.Lock()
        self._pub_conn: pika.BlockingConnection | None = None
        self._pub_ch: BlockingChannel | None = None

    # ---- publishing ---------------------------------------------------------------

    def _channel(self) -> BlockingChannel:
        if self._pub_ch is None or self._pub_ch.is_closed:
            self._pub_conn = pika.BlockingConnection(self.params)
            self._pub_ch = self._pub_conn.channel()
            self._pub_ch.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
            self._pub_ch.confirm_delivery()  # publish returns only once the broker has it
        return self._pub_ch

    def publish(self, event: Event) -> None:
        with self._pub_lock:
            try:
                self._channel().basic_publish(
                    EXCHANGE,
                    event.routing_key,
                    event.to_json().encode(),
                    pika.BasicProperties(
                        content_type="application/json", delivery_mode=2, message_id=event.event_id
                    ),
                )
            except pika.exceptions.AMQPError:
                self._pub_ch = None  # reconnect next time; the outbox row stays unsent
                raise

    # ---- consuming ----------------------------------------------------------------

    def subscribe(self, queue_name: str, bindings: list[str], handler: Handler) -> None:
        self._subs.append((queue_name, bindings, handler))

    def start(self) -> None:
        for sub in self._subs:
            t = threading.Thread(target=self._consume_forever, args=sub, name=f"rabbit:{sub[0]}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def _consume_forever(self, queue_name: str, bindings: list[str], handler: Handler) -> None:
        while not self._stop.is_set():
            try:
                self._consume(queue_name, bindings, handler)
            except pika.exceptions.AMQPError:
                log.warning("lost connection for %s; reconnecting", queue_name)
                time.sleep(self.reconnect_delay_s)

    def _consume(self, queue_name: str, bindings: list[str], handler: Handler) -> None:
        conn = pika.BlockingConnection(self.params)
        ch = conn.channel()
        ch.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
        ch.queue_declare(queue_name, durable=True)
        for key in bindings:
            ch.queue_bind(queue_name, EXCHANGE, routing_key=key)
        ch.basic_qos(prefetch_count=1)

        def on_message(channel: BlockingChannel, method: Any, _props: Any, body: bytes) -> None:
            try:
                handler(Event.from_json(body))
            except Exception:
                log.exception("handler for %s failed; message requeued", queue_name)
                time.sleep(0.5)
                channel.basic_nack(method.delivery_tag, requeue=True)
                return
            channel.basic_ack(method.delivery_tag)

        ch.basic_consume(queue_name, on_message)
        while not self._stop.is_set():
            conn.process_data_events(time_limit=1)
        conn.close()


def bus_from_env(url: str | None) -> Any:
    """``RabbitBus`` when an AMQP URL is configured, else None (the caller supplies a bus)."""
    return RabbitBus(url) if url else None
