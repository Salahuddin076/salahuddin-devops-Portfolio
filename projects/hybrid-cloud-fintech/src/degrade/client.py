"""The client wrapper: call on-prem, or degrade gracefully and queue it.

This is the piece a customer-facing AWS service imports. It calls a
``transport`` -- any ``Callable[[dict], dict]`` that reaches the on-prem
system of record (over the connectivity module's VPN link, in a real
deployment) -- and reacts to exactly two failure shapes as "the link is
down, not the request":

* ``OnPremUnavailableError`` -- raised by the transport itself.
* ``TimeoutError`` -- the stdlib's own timeout exception, so a transport
  built on ``socket``/``http.client`` with a deadline doesn't need to wrap
  its own timeout in a custom type.

On either, instead of letting the exception reach the caller (which would
turn into a failed customer-facing request), the operation is appended to
the outbox and the call returns a ``CallResult`` with
``outcome=CallOutcome.QUEUED``. Any other exception the transport raises
(a validation error, a business rejection, an auth failure) propagates
unchanged -- it is not a connectivity problem and queuing it would hide a
real bug or silently accept an invalid request.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Any, Callable

from .exceptions import OnPremUnavailableError
from .outbox import OutboxEntry


class CallOutcome(enum.Enum):
    COMPLETED = "completed"  # the on-prem call succeeded synchronously
    QUEUED = "queued"  # the link was down; the work is in the outbox for replay


@dataclass(frozen=True)
class CallResult:
    outcome: CallOutcome
    result: dict[str, Any] | None = None
    outbox_entry: OutboxEntry | None = None

    @property
    def queued(self) -> bool:
        return self.outcome is CallOutcome.QUEUED


Transport = Callable[[dict[str, Any]], dict[str, Any]]


class DegradingClient:
    def __init__(
        self,
        transport: Transport,
        outbox,
        *,
        clock: Callable[[], float] = time.time,
        on_degrade: Callable[[str, dict[str, Any], BaseException], None] | None = None,
    ) -> None:
        """
        transport   callable reaching the on-prem system; raises
                    OnPremUnavailableError or TimeoutError when the link is
                    the problem.
        outbox      an InMemoryOutbox or FileOutbox (anything with
                    .append(operation, payload)).
        clock       injected for deterministic tests.
        on_degrade  optional hook called whenever a request is queued
                    instead of completed -- the reference wires this to a
                    log line / metric emitter (see docs/operations.md); it
                    must never raise, and an exception from it is not
                    caught here on purpose so a broken hook fails loudly in
                    tests rather than silently swallowing the degrade path.
        """
        self._transport = transport
        self._outbox = outbox
        self._clock = clock
        self._on_degrade = on_degrade

    def call_or_queue(self, operation: str, payload: dict[str, Any]) -> CallResult:
        try:
            result = self._transport(payload)
        except (OnPremUnavailableError, TimeoutError) as exc:
            entry = self._outbox.append(operation, payload)
            if self._on_degrade is not None:
                self._on_degrade(operation, payload, exc)
            return CallResult(outcome=CallOutcome.QUEUED, outbox_entry=entry)
        return CallResult(outcome=CallOutcome.COMPLETED, result=result)
