"""Exceptions that signal "the on-prem link is the problem," not a request error."""

from __future__ import annotations


class OnPremUnavailableError(Exception):
    """Raised by a transport when the on-prem system of record could not be
    reached (timeout, connection refused, or any error the caller has
    classified as a connectivity failure rather than a business rejection).

    A ``DegradingClient`` catches exactly this exception type (and
    ``TimeoutError``) to decide whether to queue the work. Anything else
    -- a validation error, a business rule rejection, an auth failure --
    propagates normally: degrading the request only makes sense when the
    *link*, not the request, is at fault.
    """
