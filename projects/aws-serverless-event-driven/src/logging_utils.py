"""Structured JSON logging with a bound correlation ID.

One log record is one JSON object on one line, so CloudWatch Logs Insights
can filter on fields directly (``filter correlation_id = "..."``) without
parsing free text. The logger is deliberately tiny: no handlers, no global
configuration, and the output stream and clock are injectable for tests.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, TextIO

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}

CORRELATION_HEADER = "x-correlation-id"
CORRELATION_ATTRIBUTE = "correlationId"


def iso_timestamp(epoch_seconds: float) -> str:
    """Format an epoch timestamp as ISO 8601 UTC with millisecond precision."""
    moment = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class JsonLogger:
    """Emit one JSON object per log call, carrying any bound context fields."""

    def __init__(
        self,
        service: str,
        *,
        level: str = "INFO",
        stream: TextIO | None = None,
        clock: Callable[[], float] = time.time,
        context: dict[str, Any] | None = None,
    ) -> None:
        if level.upper() not in LEVELS:
            raise ValueError(f"unknown log level {level!r}")
        self.service = service
        self.level = level.upper()
        self._stream = stream
        self._clock = clock
        self._context = dict(context or {})

    def bind(self, **fields: Any) -> "JsonLogger":
        """Return a child logger that adds ``fields`` to every record."""
        merged = {**self._context, **fields}
        return JsonLogger(
            self.service,
            level=self.level,
            stream=self._stream,
            clock=self._clock,
            context=merged,
        )

    def debug(self, message: str, **fields: Any) -> None:
        self._emit("DEBUG", message, fields)

    def info(self, message: str, **fields: Any) -> None:
        self._emit("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("ERROR", message, fields)

    def _emit(self, level: str, message: str, fields: dict[str, Any]) -> None:
        if LEVELS[level] < LEVELS[self.level]:
            return
        record = {
            "timestamp": iso_timestamp(self._clock()),
            "level": level,
            "service": self.service,
            "message": message,
            **self._context,
            **fields,
        }
        stream = self._stream if self._stream is not None else sys.stdout
        stream.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
