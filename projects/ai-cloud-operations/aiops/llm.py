"""LLM provider interface, with a no-op default.

Design intent: the entire pipeline must run with **zero external calls and
zero API keys by default**. Every stage that could use an LLM calls it
through this interface, and the default implementation
(``NoOpLLMProvider``) never performs network I/O — it simply declines,
which tells the caller (``aiops.summarize``) to fall back to the
deterministic template summary.

How a real provider would plug in
----------------------------------
Implement :class:`LLMProvider` (``name`` + ``summarize``) in your own
module, e.g.::

    class AnthropicLLMProvider:
        name = "anthropic"

        def __init__(self, api_key: str, model: str = "claude-...-latest"):
            self._api_key = api_key
            self._model = model

        def summarize(self, prompt: str, max_tokens: int) -> str | None:
            # Call the provider's SDK/HTTP API here. Must:
            #  - only ever receive text that already passed aiops.redact.redact
            #    (enforced by aiops.summarize.summarize, not by this class)
            #  - respect max_tokens as an output token cap
            #  - return None (never raise) on any failure, so the pipeline
            #    degrades to the template summary instead of crashing
            ...

No such provider is implemented, imported, or network-capable in this
codebase. Wiring one in is a one-line change in the caller
(``SummaryConfig(provider=AnthropicLLMProvider(...))``); nothing else in
the pipeline changes, and nothing here ever ships credentials.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Anything with a ``name`` and a ``summarize`` method can be plugged in."""

    name: str

    def summarize(self, prompt: str, max_tokens: int) -> str | None:
        """Return a summary, or ``None`` to signal "fall back to template"."""
        ...


class NoOpLLMProvider:
    """Default provider. Makes no network call and needs no API key."""

    name = "noop"

    def summarize(self, prompt: str, max_tokens: int) -> str | None:
        return None
