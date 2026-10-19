"""Redact log content before it is ever handed to an (optional) LLM call.

This runs unconditionally in ``summarize.summarize`` whenever the LLM path
is taken, regardless of which provider is configured — including the
default no-op provider, so the redaction gate is exercised even though no
network call actually happens by default. The patterns are intentionally
simple regexes, not a full PII engine: this is a basic, auditable
guardrail, not a compliance tool.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# key=value / key: value pairs that look like credentials.
_KEYVALUE_SECRET_RE = re.compile(
    r"(?i)\b([\w.-]*(?:api[_-]?key|token|secret|password|passwd)[\w.-]*\s*[:=]\s*)(['\"]?)([A-Za-z0-9/_+.\-]{6,})\2"
)
# bare provider-shaped API keys (e.g. GitHub, Slack, generic sk-/pk- prefixes).
_BARE_SECRET_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|xox[baprs]|sk|pk)[-_][A-Za-z0-9]{8,}\b")

REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_EMAIL_RE, "[REDACTED_EMAIL]"),
    (_IPV4_RE, "[REDACTED_IP]"),
)


def redact(text: str) -> str:
    """Return ``text`` with emails, IPs and credential-shaped strings masked."""
    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    out = _KEYVALUE_SECRET_RE.sub(lambda m: f"{m.group(1)}[REDACTED_SECRET]", out)
    out = _BARE_SECRET_RE.sub("[REDACTED_SECRET]", out)
    return out


def redact_lines(lines: list[str]) -> list[str]:
    return [redact(line) for line in lines]
