"""Structured JSON logging (ADR-017).

One log line == one JSON object. Idempotent — safe to call multiple times
(e.g., in tests). Uvicorn's access/error loggers are re-routed through the
same formatter so every line in a production log is parseable.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_LOGGERS_TO_REROUTE = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Any extras attached via `logger.info("...", extra={"run_id": ...})`
        # get merged in; reserved LogRecord attributes are skipped.
        reserved = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)
        reserved.update({"message", "asctime"})
        for key, value in record.__dict__.items():
            if key not in reserved and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger and re-route uvicorn."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in _LOGGERS_TO_REROUTE:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True  # bubble up to root -> JSON handler
