#!/usr/bin/env python3
"""Render docs/comparison.yaml into a Markdown comparison table.

The structured data is the source of truth; this script and
tests/test_comparison.py are what keep it from silently losing a cloud or a
dimension. Usage:

    python3 scripts/render_comparison.py [docs/comparison.yaml]
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml_lite

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = PROJECT / "docs" / "comparison.yaml"


def load_comparison(path: Path = DEFAULT_PATH) -> dict:
    data = yaml_lite.load(path.read_text())
    validate(data)
    return data


def validate(data: dict) -> None:
    """Raise ValueError if the data is missing a cloud or a dimension value."""
    clouds = data.get("clouds")
    dimensions = data.get("dimensions")
    if not clouds or len(clouds) < 2:
        raise ValueError("comparison.yaml must list at least two clouds")
    cloud_ids = [c["id"] for c in clouds]
    if len(set(cloud_ids)) != len(cloud_ids):
        raise ValueError(f"duplicate cloud ids: {cloud_ids}")
    if not dimensions:
        raise ValueError("comparison.yaml must list at least one dimension")
    for dim in dimensions:
        missing = [cid for cid in cloud_ids if not dim.get("values", {}).get(cid)]
        if missing:
            raise ValueError(f"dimension {dim['id']!r} is missing values for: {missing}")


def render_markdown(data: dict) -> str:
    clouds = data["clouds"]
    dimensions = data["dimensions"]

    header = "| Dimension | " + " | ".join(c["name"] for c in clouds) + " |"
    separator = "|" + "---|" * (len(clouds) + 1)
    rows = [header, separator]
    for dim in dimensions:
        cells = [dim["values"][c["id"]] for c in clouds]
        rows.append("| " + dim["label"] + " | " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    try:
        data = load_comparison(path)
    except ValueError as exc:
        print(f"comparison.yaml is invalid: {exc}", file=sys.stderr)
        return 1
    print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
