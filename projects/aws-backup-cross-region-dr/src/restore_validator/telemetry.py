"""Structured JSON logs and CloudWatch embedded metric format (EMF) lines.

A log record is one JSON object on one line, so Logs Insights can filter on
fields directly. An EMF line is also one JSON object on one line, written to
stdout: CloudWatch Logs extracts the metric from it asynchronously, so the
Lambda needs no ``cloudwatch:PutMetricData`` permission and makes no extra
API call on the hot path.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, TextIO

METRIC_NAME = "RestoreValidationSucceeded"


def iso_timestamp(epoch_seconds: float) -> str:
    moment = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def emf_record(
    *,
    namespace: str,
    resource_type: str,
    succeeded: bool,
    epoch_seconds: float,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an EMF document for ``RestoreValidationSucceeded`` (1 or 0).

    The single dimension set is ``ResourceType``, so the alarm and dashboard
    can split RDS from S3. Extra properties (job ID, ARN) ride along as
    searchable log fields without becoming dimensions, which would multiply
    the number of custom metrics billed.
    """
    return {
        "_aws": {
            "Timestamp": int(epoch_seconds * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [["ResourceType"]],
                    "Metrics": [{"Name": METRIC_NAME, "Unit": "Count"}],
                }
            ],
        },
        "ResourceType": resource_type,
        METRIC_NAME: 1 if succeeded else 0,
        **(properties or {}),
    }


class Telemetry:
    def __init__(self, service: str, *, stream: TextIO | None = None, clock: Callable[[], float]) -> None:
        self.service = service
        self._stream = stream
        self._clock = clock

    def _write(self, record: dict[str, Any]) -> None:
        stream = self._stream if self._stream is not None else sys.stdout
        stream.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")

    def log(self, level: str, message: str, **fields: Any) -> None:
        self._write(
            {
                "timestamp": iso_timestamp(self._clock()),
                "level": level,
                "service": self.service,
                "message": message,
                **fields,
            }
        )

    def metric(self, *, namespace: str, resource_type: str, succeeded: bool, **properties: Any) -> None:
        self._write(
            emf_record(
                namespace=namespace,
                resource_type=resource_type,
                succeeded=succeeded,
                epoch_seconds=self._clock(),
                properties=properties,
            )
        )
