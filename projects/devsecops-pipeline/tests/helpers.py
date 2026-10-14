"""Shared test helpers: import paths and fixture locations."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
POLICY_DIR = PROJECT / "policy"
APP_DIR = PROJECT / "app"
FIXTURES = PROJECT / "tests" / "fixtures"
WORKFLOW_FIXTURES = FIXTURES / "workflows"
TRIVYIGNORE_FIXTURES = FIXTURES / "trivyignore"
REPO_ROOT = PROJECT.parent.parent
REPO_WORKFLOWS = REPO_ROOT / ".github" / "workflows"
OWN_WORKFLOWS = [REPO_WORKFLOWS / "devsecops-reusable.yml", REPO_WORKFLOWS / "devsecops-pipeline.yml"]

for p in (POLICY_DIR, APP_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def fixture(name: str) -> str:
    return (WORKFLOW_FIXTURES / name).read_text(encoding="utf-8")
