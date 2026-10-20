"""Shared test setup: paths."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = PROJECT / "terraform"
CHART_DIR = PROJECT / "helm" / "portable-service"
DOCS_DIR = PROJECT / "docs"
ARGOCD_DIR = PROJECT / "argocd"
SCRIPTS_DIR = PROJECT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
