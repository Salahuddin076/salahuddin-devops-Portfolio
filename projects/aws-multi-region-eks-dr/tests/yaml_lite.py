"""A small block-YAML reader for `helm template` output (stdlib has no YAML).

Supports what this chart renders: `---` document separators, comments,
nested mappings, block sequences (including `- key: value` items), plain,
single- and double-quoted scalars, and JSON-style flow sequences. Anything
else raises, so a template change that outgrows it fails loudly instead of
being misread.
"""

from __future__ import annotations

import json
import re
from typing import Any

_INT = re.compile(r"^-?[0-9]+$")


def _scalar(text: str) -> Any:
    t = text.strip()
    if t == "" or t in ("null", "~"):
        return None
    if t in ("true", "false"):
        return t == "true"
    if _INT.match(t):
        return int(t)
    if t.startswith('"'):
        return json.loads(t)
    if t.startswith("'"):
        if not t.endswith("'"):
            raise ValueError(f"unterminated single-quoted scalar: {t}")
        return t[1:-1].replace("''", "'")
    if t.startswith("[") or t.startswith("{"):
        return json.loads(t)
    return t


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_key(text: str) -> tuple[str, str]:
    # key: value  (keys in this chart never contain ": ")
    if text.endswith(":"):
        return text[:-1].strip(), ""
    key, sep, rest = text.partition(": ")
    if not sep:
        raise ValueError(f"expected 'key: value', got {text!r}")
    return key.strip(), rest


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if i >= len(lines):
        return None, i
    if lines[i][1].startswith("- "):
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_value(lines, i, indent, rest):
    if rest.strip():
        return _scalar(rest), i + 1
    if i + 1 < len(lines) and (lines[i + 1][0] > indent or
                               (lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "))):
        return _parse_block(lines, i + 1, lines[i + 1][0])
    return None, i + 1


def _parse_map(lines, i, indent):
    out: dict[str, Any] = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
        key, rest = _split_key(lines[i][1])
        out[key], i = _parse_value(lines, i, indent, rest)
    if i < len(lines) and lines[i][0] > indent:
        raise ValueError(f"unexpected indentation at {lines[i][1]!r}")
    return out, i


def _parse_seq(lines, i, indent):
    out: list[Any] = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
        body = lines[i][1][2:]
        inner = indent + 2
        if ": " in body or body.endswith(":"):
            # "- key: value" starts a mapping whose keys sit at indent + 2.
            lines[i] = (inner, body)
            item, i = _parse_map(lines, i, inner)
        else:
            item, i = _scalar(body), i + 1
        out.append(item)
    return out, i


def load_all(text: str) -> list[Any]:
    docs = []
    for chunk in re.split(r"(?m)^---\s*$", text):
        lines = []
        for raw in chunk.splitlines():
            line = _strip_comment(raw)
            if line.strip():
                lines.append((len(line) - len(line.lstrip(" ")), line.strip()))
        if not lines:
            continue
        doc, end = _parse_block(lines, 0, lines[0][0])
        if end != len(lines):
            raise ValueError(f"could not parse past {lines[end][1]!r}")
        docs.append(doc)
    return docs
