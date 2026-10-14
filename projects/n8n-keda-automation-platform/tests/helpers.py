"""Shared test setup: paths, and scripts/ on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT / "scripts"
CHART_DIR = PROJECT / "helm" / "n8n-platform"
TERRAFORM_DIR = PROJECT / "terraform"
MODULE_DIR = TERRAFORM_DIR / "modules" / "n8n-platform"
FIXTURES = PROJECT / "tests" / "fixtures"
SAMPLE_CSV = PROJECT / "sample-data" / "queue-depth.csv"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
