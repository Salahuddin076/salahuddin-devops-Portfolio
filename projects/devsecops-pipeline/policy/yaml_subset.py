"""A small block-YAML reader for GitHub Actions workflow files.

PyYAML is deliberately not used (stdlib only, so the linter runs anywhere
with python3). This covers the subset that workflow files use in practice:

- block mappings and block sequences, nested by indentation;
- `- key: value` sequence items that open a mapping;
- plain, single-quoted and double-quoted scalars;
- block scalars (`|`, `|-`, `>`, `>-`, ...), kept as raw text;
- flow sequences of plain scalars (`[main, develop]`) and `{}` / `[]`;
- full-line and trailing comments (`# ...` after whitespace, outside quotes).

Not supported: anchors/aliases, multi-document streams, complex keys,
multi-line flow collections. Anything unexpected is kept as a string, so a
rule sees a value it does not match rather than the parser crashing.

Every mapping records the 1-based source line of each key in `.lines`, and
every sequence records the line of each item, so findings can point at the
exact line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["YMap", "YList", "parse", "YamlSubsetError"]


class YamlSubsetError(ValueError):
    """Raised for structure this reader cannot make sense of."""


class YMap(dict):
    """dict with the source line of each key in `.lines`."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: dict[str, int] = {}


class YList(list):
    """list with the source line of each item in `.lines`."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[int] = []


@dataclass
class _Line:
    indent: int
    text: str  # stripped of indentation and trailing comment
    raw: str  # original line (needed for block scalars)
    lineno: int


_KEY_RE = re.compile(r"""^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s'"#\-?:,\[\]{}][^:#]*?|[^\s'"#?:,\[\]{}])\s*:(?:\s+(.*)|)$""")
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?[0-9]?$")


def _strip_comment(text: str) -> str:
    """Remove a trailing `# comment` that is outside quotes."""
    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"') and (i == 0 or text[i - 1] in " \t:-[{,"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return bytes(v[1:-1], "utf-8").decode("unicode_escape") if "\\" in v else v[1:-1]
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def _scalar(value: str, lineno: int):
    v = value.strip()
    if v == "{}":
        return YMap()
    if v.startswith("[") and v.endswith("]"):
        out = YList()
        inner = v[1:-1].strip()
        if inner:
            for part in inner.split(","):
                out.append(_unquote(part))
                out.lines.append(lineno)
        return out
    return _unquote(v)


class _Parser:
    def __init__(self, text: str) -> None:
        self.raw_lines = text.splitlines()
        self.lines: list[_Line] = []
        for n, raw in enumerate(self.raw_lines, start=1):
            if "\t" in raw[: len(raw) - len(raw.lstrip())]:
                raise YamlSubsetError(f"line {n}: tab used for indentation")
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped in ("---", "..."):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            self.lines.append(_Line(indent, _strip_comment(raw.strip()), raw, n))
        self.i = 0

    # -- helpers -----------------------------------------------------------
    def _peek(self) -> _Line | None:
        return self.lines[self.i] if self.i < len(self.lines) else None

    @staticmethod
    def _is_item(line: _Line) -> bool:
        return line.text == "-" or line.text.startswith("- ")

    def _block_scalar(self, parent_indent: int, start_lineno: int) -> str:
        """Collect raw lines (including blank/comment ones) deeper than parent."""
        collected: list[str] = []
        n = start_lineno  # 1-based line of the `key: |` line
        body_indent = None
        while n < len(self.raw_lines):
            raw = self.raw_lines[n]
            if raw.strip() == "":
                collected.append("")
                n += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= parent_indent:
                break
            if body_indent is None:
                body_indent = indent
            collected.append(raw[min(indent, body_indent):])
            n += 1
        # skip parsed lines that belong to the block scalar
        while self.i < len(self.lines) and self.lines[self.i].lineno <= n:
            self.i += 1
        while collected and collected[-1] == "":
            collected.pop()
        return "\n".join(collected)

    # -- grammar -----------------------------------------------------------
    def parse_block(self, indent: int):
        line = self._peek()
        if line is None or line.indent < indent:
            return None
        if self._is_item(line):
            return self.parse_list(line.indent)
        return self.parse_map(line.indent)

    def parse_value(self, rest: str, owner: _Line):
        """Value after `key:` or `- ` on `owner`'s line."""
        if rest == "" or rest is None:
            nxt = self._peek()
            if nxt is None:
                return None
            if nxt.indent > owner.indent:
                return self.parse_block(nxt.indent)
            # `key:` followed by a sequence at the same indent is valid YAML
            if nxt.indent == owner.indent and self._is_item(nxt) and not self._is_item(owner):
                return self.parse_list(nxt.indent)
            return None
        if _BLOCK_SCALAR_RE.match(rest):
            return self._block_scalar(owner.indent, owner.lineno)
        return _scalar(rest, owner.lineno)

    def parse_map(self, indent: int) -> YMap:
        out = YMap()
        while True:
            line = self._peek()
            if line is None or line.indent != indent or self._is_item(line):
                if line is not None and line.indent > indent:
                    raise YamlSubsetError(f"line {line.lineno}: unexpected indentation")
                return out
            m = _KEY_RE.match(line.text)
            if not m:
                raise YamlSubsetError(f"line {line.lineno}: expected 'key: value', got {line.text!r}")
            key = _unquote(m.group(1))
            self.i += 1
            out[key] = self.parse_value((m.group(2) or "").strip(), line)
            out.lines[key] = line.lineno

    def parse_list(self, indent: int) -> YList:
        out = YList()
        while True:
            line = self._peek()
            if line is None or line.indent != indent or not self._is_item(line):
                return out
            content = line.text[1:].lstrip()
            out.lines.append(line.lineno)
            if content == "":
                self.i += 1
                out.append(self.parse_value("", line))
                continue
            offset = len(line.text) - len(content)
            if _KEY_RE.match(content):
                # `- key: value` opens a mapping at the column of `key`
                self.lines[self.i] = _Line(indent + offset, content, line.raw, line.lineno)
                out.append(self.parse_map(indent + offset))
            else:
                self.i += 1
                if _BLOCK_SCALAR_RE.match(content):
                    out.append(self._block_scalar(indent, line.lineno))
                else:
                    out.append(_scalar(content, line.lineno))


def parse(text: str):
    """Parse workflow YAML text into YMap/YList/str values."""
    p = _Parser(text)
    if not p.lines:
        return YMap()
    first = p.lines[0]
    if first.indent != 0:
        raise YamlSubsetError(f"line {first.lineno}: document must start at column 0")
    doc = p.parse_block(0)
    leftover = p._peek()
    if leftover is not None:
        raise YamlSubsetError(f"line {leftover.lineno}: could not parse {leftover.text!r}")
    return doc
