"""Shared test setup: paths."""

from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = PROJECT / "terraform"
CHART_DIR = PROJECT / "helm" / "keyvault-csi-demo"
