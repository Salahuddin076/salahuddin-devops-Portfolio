"""Minimal block-YAML reader for rendered Kubernetes manifests (stdlib has no YAML).

Shared with projects/eks-secrets-store-csi (same file), so both projects
parse rendered charts the same way.

Handles what `helm template` emits for this chart and what the fixtures use:
`---` separators, comments, nested mappings, block sequences (with
`- key: value` items), plain / single- / double-quoted scalars, JSON-style
flow collections, and literal / folded block scalars (`|`, `|-`, `>`, `>-`),
which a SecretProviderClass needs for its `objects` parameter. Anything
outside that raises ValueError, so a manifest it can't read fails loudly
instead of being half-checked.
"""

from __future__ import annotations

import json
import re
from typing import Any

_INT = re.compile(r"^-?[0-9]+$")
_BLOCK = re.compile(r"^[|>][+-]?$")


def scalar(text: str) -> Any:
    t = text.strip()
    if t in ("", "null", "~"):
        return None
    if t in ("true", "false"):
        return t == "true"
    if _INT.match(t):
        return int(t)
    if t.startswith('"'):
        return json.loads(t)
    if t.startswith("'"):
        if len(t) < 2 or not t.endswith("'"):
            raise ValueError(f"unterminated single-quoted scalar: {t}")
        return t[1:-1].replace("''", "'")
    if t[0] in "[{":
        return json.loads(t)
    return t


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and (i == 0 or line[i - 1] in " :-[{,"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            return line[:i].rstrip()
    return line.rstrip()


class _Reader:
    def __init__(self, raw_lines: list[str]) -> None:
        self.raw = raw_lines          # original lines, needed for block scalars
        self.lines: list[tuple[int, str, int]] = []  # (indent, text, raw index)
        for idx, raw in enumerate(raw_lines):
            text = _strip_comment(raw)
            if text.strip():
                self.lines.append((len(text) - len(text.lstrip(" ")), text.strip(), idx))
        self.i = 0

    def block_scalar(self, header: str, parent_indent: int, raw_idx: int) -> str:
        # Consume raw lines more indented than the parent, comments included.
        body, j = [], raw_idx + 1
        while j < len(self.raw):
            line = self.raw[j]
            if line.strip() and (len(line) - len(line.lstrip(" "))) <= parent_indent:
                break
            body.append(line)
            j += 1
        while self.i < len(self.lines) and self.lines[self.i][2] < j:
            self.i += 1
        while body and not body[-1].strip():
            body.pop()
        if not body:
            return ""
        indent = min(len(b) - len(b.lstrip(" ")) for b in body if b.strip())
        lines = [b[indent:] for b in body]
        text = "\n".join(lines) if header[0] == "|" else " ".join(x.strip() for x in lines)
        return text if header.endswith("-") else text + "\n"

    def value(self, indent: int, rest: str, raw_idx: int) -> Any:
        rest = rest.strip()
        if _BLOCK.match(rest):
            return self.block_scalar(rest, indent, raw_idx)
        if rest:
            return scalar(rest)
        if self.i < len(self.lines):
            nxt_indent, nxt_text, _ = self.lines[self.i]
            if nxt_indent > indent or (nxt_indent == indent and nxt_text.startswith("- ")):
                return self.block(nxt_indent)
        return None

    def block(self, indent: int) -> Any:
        if self.lines[self.i][1].startswith("- ") or self.lines[self.i][1] == "-":
            return self.seq(indent)
        return self.map(indent)

    def map(self, indent: int) -> dict:
        out: dict[str, Any] = {}
        while self.i < len(self.lines):
            ind, text, raw_idx = self.lines[self.i]
            if ind != indent or text.startswith("- "):
                break
            key, rest = split_key(text)
            self.i += 1
            out[key] = self.value(indent, rest, raw_idx)
        if self.i < len(self.lines) and self.lines[self.i][0] > indent:
            raise ValueError(f"unexpected indentation at {self.lines[self.i][1]!r}")
        return out

    def seq(self, indent: int) -> list:
        out: list[Any] = []
        while self.i < len(self.lines):
            ind, text, raw_idx = self.lines[self.i]
            if ind != indent or not (text.startswith("- ") or text == "-"):
                break
            body = text[2:] if text != "-" else ""
            inner = indent + 2
            if body and (_looks_like_key(body)):
                self.lines[self.i] = (inner, body, raw_idx)
                out.append(self.map(inner))
            elif body:
                self.i += 1
                out.append(scalar(body))
            else:
                self.i += 1
                out.append(self.block(self.lines[self.i][0]) if self.i < len(self.lines) else None)
        return out


def _looks_like_key(text: str) -> bool:
    if text[0] in "\"'[{":
        return False
    return ": " in text or text.endswith(":")


def split_key(text: str) -> tuple[str, str]:
    if text.endswith(":") and ": " not in text:
        key, rest = text[:-1], ""
    else:
        key, sep, rest = text.partition(": ")
        if not sep:
            raise ValueError(f"expected 'key: value', got {text!r}")
    key = key.strip()
    if key[:1] in "\"'":
        key = scalar(key)
    return key, rest


def load_all(text: str) -> list[Any]:
    docs = []
    for chunk in re.split(r"(?m)^---[^\n]*$", text):
        reader = _Reader(chunk.splitlines())
        if not reader.lines:
            continue
        doc = reader.block(reader.lines[0][0])
        if reader.i != len(reader.lines):
            raise ValueError(f"could not parse past {reader.lines[reader.i][1]!r}")
        if doc is not None:
            docs.append(doc)
    return docs
