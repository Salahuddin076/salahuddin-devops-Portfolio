"""Shared test setup: `src` on sys.path, a fixed clock, and orchestrator builders."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT / "src"
CHART_DIR = PROJECT / "helm" / "dr-app"
TERRAFORM_DIR = PROJECT / "terraform"
EXAMPLE_CONFIG = PROJECT / "config" / "failover.example.json"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from failover.audit import AuditLog  # noqa: E402
from failover.config import load_config  # noqa: E402
from failover.fakes import FakeCloud  # noqa: E402
from failover.orchestrator import Orchestrator  # noqa: E402
from failover.ports import Adapters  # noqa: E402
from failover.state import MemoryStateStore  # noqa: E402

GCID = "dr-app-global"
PRIMARY = "us-east-1"
DR = "us-west-2"
START = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


class Clock:
    """Advances one second per call so audit timestamps are ordered and fixed."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


def config():
    return load_config(EXAMPLE_CONFIG)


def build(scenario: str = "healthy", world: FakeCloud | None = None, store=None, audit=None,
          actor: str = "oncall-a"):
    """Return (orchestrator, world, store, audit) wired to fakes."""
    world = world or FakeCloud.scenario(scenario)
    store = store or MemoryStateStore()
    audit = audit or AuditLog(None)
    orch = Orchestrator(config(), Adapters(world, world, world, world), store, audit,
                        clock=Clock(), actor=actor)
    return orch, world, store, audit


def rebuild(world: FakeCloud, store, audit, actor: str = "oncall-a"):
    """A fresh orchestrator over the same world/state/audit (a new CLI invocation)."""
    return Orchestrator(config(), Adapters(world, world, world, world), store, audit,
                        clock=Clock(START + timedelta(hours=1)), actor=actor)


class CrashingStore(MemoryStateStore):
    """Raises on the Nth save, as if the tool died right after an API call
    succeeded but before its result was recorded."""

    def __init__(self, crash_on_save: int) -> None:
        super().__init__()
        self.saves = 0
        self.crash_on_save = crash_on_save

    def save(self, state) -> None:
        self.saves += 1
        if self.saves == self.crash_on_save:
            raise KeyboardInterrupt("simulated crash of the failover tool")
        super().save(state)
