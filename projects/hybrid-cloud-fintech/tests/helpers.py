"""Shared test helpers: import paths and small fakes."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT / "src"
TERRAFORM = PROJECT / "terraform"
ANSIBLE = PROJECT / "ansible"

for p in (SRC_DIR,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class FakeClock:
    def __init__(self, start: float = 1_792_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 1.0) -> None:
        self.now += seconds


class CountingIds:
    def __init__(self, prefix: str = "id") -> None:
        self._n = 0
        self._prefix = prefix

    def __call__(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:04d}"
