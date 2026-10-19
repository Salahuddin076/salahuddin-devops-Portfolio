"""Shared test setup: paths, and scripts/ on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT / "scripts"
CHART_DIR = PROJECT / "helm" / "multiarch-app"
TERRAFORM_DIR = PROJECT / "terraform"
DOCS_DIR = PROJECT / "docs"
FIXTURES = PROJECT / "tests" / "fixtures"

for _p in (SCRIPTS_DIR,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
