"""Patterns shared by scan_manifests.py and find_hardcoded_secrets.py."""

from __future__ import annotations

import math
import re
from collections import Counter

AWS_ACCESS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")
PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")

# A name is secret-looking when one of its `_`/`-`/`.` separated tokens is in
# this set ("DB_PASSWORD", "api-key", "GITHUB_TOKEN"). Plural or compound
# names that describe *where* secrets are ("SECRETS_DIR") don't match.
SECRET_NAME_TOKENS = {"PASSWORD", "PASSWD", "PWD", "PASS", "SECRET", "TOKEN", "APIKEY",
                      "CREDENTIAL", "CREDENTIALS", "PRIVATEKEY"}
SECRET_NAME_PAIRS = {("API", "KEY"), ("ACCESS", "KEY"), ("SECRET", "KEY"), ("PRIVATE", "KEY"),
                     ("CLIENT", "SECRET"), ("AUTH", "TOKEN")}
# Names that point at a secret instead of holding one (the `_FILE` convention).
REFERENCE_SUFFIXES = ("FILE", "PATH", "DIR", "NAME", "ARN", "ID", "REF", "URL", "SECONDS", "MOUNT")

_BASE64ISH = re.compile(r"^[A-Za-z0-9+/=_\-]+$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")


def name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[_\-.\s]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).upper()) if t]


def is_secret_name(name: str) -> bool:
    tokens = name_tokens(name)
    if not tokens or tokens[-1] in REFERENCE_SUFFIXES:
        return False
    if any(t in SECRET_NAME_TOKENS for t in tokens):
        return True
    return any(pair in SECRET_NAME_PAIRS for pair in zip(tokens, tokens[1:]))


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def is_high_entropy(text: str, min_len: int = 20) -> bool:
    """Random-looking token: long, one charset, and high Shannon entropy.

    Hex needs >= 32 chars and 3.0 bits/char; base64-ish needs 4.0 bits/char
    and a mix of upper, lower and digits (rules out words_with_underscores and
    kebab-case identifiers).
    """
    t = text.strip()
    if len(t) < min_len or not _BASE64ISH.match(t):
        return False
    if _HEX.match(t):
        return len(t) >= 32 and shannon_entropy(t) >= 3.0
    classes = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]"))
    return classes == 3 and shannon_entropy(t) >= 4.0


def looks_like_secret_value(text: str) -> str | None:
    """Return a short reason when a value itself looks like a credential."""
    if AWS_ACCESS_KEY_ID.search(text):
        return "AWS access key ID"
    if PRIVATE_KEY_HEADER.search(text):
        return "private key"
    if is_high_entropy(text):
        return "high-entropy string"
    return None


def mask(value: str) -> str:
    """Show enough to find the value, never enough to use it."""
    value = value.strip()
    if len(value) <= 8:
        return f"<{len(value)} chars>"
    return f"{value[:4]}...<{len(value)} chars>"
