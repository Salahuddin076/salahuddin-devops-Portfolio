"""Replay: drain the outbox once the on-prem link is back.

This is a separate, explicit step from ``DegradingClient`` on purpose. The
customer-facing request path only ever appends to the outbox; it never
retries inline, so a customer-facing request never blocks on-prem
reachability twice. Replay runs out of band -- a cron/systemd timer next to
the FileOutbox, or a small Lambda/Job hitting a shared store in a real
deployment (see docs/operations.md) -- and is itself idempotent: re-running
it against a file with no pending entries is a no-op, and each attempt that
still fails just increments ``attempts`` until ``max_attempts``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .exceptions import OnPremUnavailableError
from .outbox import OutboxEntry


@dataclass
class ReplaySummary:
    attempted: int = 0
    succeeded: list[str] = field(default_factory=list)
    still_pending: list[str] = field(default_factory=list)
    permanently_failed: list[str] = field(default_factory=list)

    @property
    def all_drained(self) -> bool:
        return not self.still_pending


def replay_pending(
    outbox,
    transport: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_attempts: int = 5,
) -> ReplaySummary:
    """Attempt every pending entry once against ``transport``.

    An entry that succeeds is marked done. An entry that fails with
    ``OnPremUnavailableError``/``TimeoutError`` again has its attempt count
    incremented and is left pending (or moved to ``failed`` once
    ``max_attempts`` is reached -- see ``outbox.mark_attempt_failed``). Any
    other exception propagates: a transport bug or a permanently invalid
    payload should not be swallowed into silent retries forever.
    """
    summary = ReplaySummary()
    for entry in outbox.pending():
        summary.attempted += 1
        try:
            transport(entry.payload)
        except (OnPremUnavailableError, TimeoutError) as exc:
            updated = outbox.mark_attempt_failed(entry.id, str(exc), max_attempts=max_attempts)
            if updated.status.value == "failed":
                summary.permanently_failed.append(entry.id)
            else:
                summary.still_pending.append(entry.id)
            continue
        outbox.mark_done(entry.id)
        summary.succeeded.append(entry.id)
    return summary
