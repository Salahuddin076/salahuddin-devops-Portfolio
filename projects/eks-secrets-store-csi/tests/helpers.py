"""Shared test setup: paths, and app/ + scripts/ on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT / "app"
SCRIPTS_DIR = PROJECT / "scripts"
CHART_DIR = PROJECT / "helm" / "secure-frontend"
TERRAFORM_DIR = PROJECT / "terraform"
FIXTURES = PROJECT / "tests" / "fixtures"

for _p in (APP_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def write_secrets(directory: Path, values: dict[str, str]) -> None:
    """Lay files out exactly like the CSI driver (the drill's atomic writer)."""
    import secret_rotation_drill

    secret_rotation_drill.write_version(directory, values)
