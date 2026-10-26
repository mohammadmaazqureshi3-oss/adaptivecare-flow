"""Structured logs with case ids (plan C4-06): one JSON object per line, for every service.

``configure_logging("worklist")`` installs the formatter on the root logger once per process.
Event handlers wrap their work in ``case_context(event.case_id)``; every line logged inside,
by any module, then carries ``case_id``, so all of one patient case's log lines can be found
with one filter (``jq 'select(.case_id == "…")'``). Fields: ``ts``, ``level``, ``service``,
``logger``, ``msg``, ``case_id`` and, when given as ``extra``, ``event_type``, ``event_id``,
``pathway``, ``version``, ``status``. ``LOG_FORMAT=text`` switches to plain lines for reading
in a terminal. Patient names never reach a log: events carry record numbers only.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

CASE_ID: ContextVar[str | None] = ContextVar("case_id", default=None)
EXTRA_FIELDS = ("event_type", "event_id", "pathway", "version", "status")
SERVICES = frozenset(
    {"auth", "designer", "verifier", "simulator", "deployer", "engine", "worklist", "patient", "ml", "scores",
     "gateway"}
)  # fmt: skip
_MARK = "_adaptivecare_handler"


@contextmanager
def case_context(case_id: str | None) -> Iterator[None]:
    """Every log line inside this block (in this thread) carries ``case_id``."""
    token = CASE_ID.set(case_id)
    try:
        yield
    finally:
        CASE_ID.reset(token)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            # In the one-process dev stack the logger's first name part is the real service.
            "service": top if (top := record.name.split(".")[0]) in SERVICES else self.service,
            "logger": record.name,
            "msg": record.getMessage(),
            "case_id": getattr(record, "case_id", None) or CASE_ID.get(),
        }
        line |= {k: getattr(record, k) for k in EXTRA_FIELDS if hasattr(record, k)}
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Install the JSON (or, with ``LOG_FORMAT=text``, plain) handler once per process."""
    root = logging.getLogger()
    if any(getattr(h, _MARK, False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "json") == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter(service))
    setattr(handler, _MARK, True)
    root.addHandler(handler)
    root.setLevel(level)
