"""Graceful-degradation pattern for the hybrid-cloud-fintech reference.

When the private link to on-prem systems of record is impaired, customer-
facing AWS services must keep accepting requests rather than fail hard.
This package is the standard-library reference implementation of that
pattern: a thin client wrapper that calls an on-prem-dependent transport
and, on a connectivity failure or timeout, defers the work to a local
outbox instead of raising, plus a replay mechanism that drains the outbox
once the link recovers.
"""

from .exceptions import OnPremUnavailableError
from .outbox import OutboxEntry, OutboxStatus, InMemoryOutbox, FileOutbox
from .client import CallOutcome, CallResult, DegradingClient
from .replay import ReplaySummary, replay_pending

__all__ = [
    "OnPremUnavailableError",
    "OutboxEntry",
    "OutboxStatus",
    "InMemoryOutbox",
    "FileOutbox",
    "CallOutcome",
    "CallResult",
    "DegradingClient",
    "ReplaySummary",
    "replay_pending",
]
