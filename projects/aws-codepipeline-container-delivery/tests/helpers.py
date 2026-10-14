"""Shared test setup: put app/ and scripts/ on sys.path."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
BUILDSPEC_DIR = os.path.join(PROJECT_ROOT, "buildspec")
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "tests", "fixtures")

for path in (APP_DIR, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
