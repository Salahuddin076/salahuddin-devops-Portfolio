"""Shared test setup: paths, scripts/ on sys.path, and a scratch copy of the config repo."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT / "scripts"
APP_REPO = PROJECT / "app-repo"
CONFIG_REPO = PROJECT / "config-repo"
CHART_DIR = CONFIG_REPO / "charts" / "orders-api"
ENVS = ("dev", "staging", "prod")
FIXTURES = PROJECT / "tests" / "fixtures"
SAMPLES = PROJECT / "sample-data"
REPO_ROOT = PROJECT.parent.parent
CRD_SCHEMA_LOCATION = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
                       "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class ScratchRepo:
    """Context manager: a throwaway copy of config-repo in a temp dir."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory(prefix="gitops-test-")
        self.path = Path(self._tmp.name) / "config-repo"
        shutil.copytree(CONFIG_REPO, self.path)
        return self.path

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()
