"""Shared paths for the test suites; puts scripts/ on the import path."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT / "scripts"
SAMPLE_DIR = PROJECT / "sample-data"
SAMPLE_BUILD = SAMPLE_DIR / "build"
SAMPLE_MANIFEST = SAMPLE_DIR / "remote-manifest.json"
HEADERS_GOOD = SAMPLE_DIR / "headers-good.txt"
HEADERS_BAD = SAMPLE_DIR / "headers-bad.txt"
TERRAFORM_DIR = PROJECT / "terraform"
STATIC_SITE_MODULE = TERRAFORM_DIR / "modules" / "static-site"
FUNCTION_JS = STATIC_SITE_MODULE / "functions" / "uri-rewrite.js"
OIDC_MODULE = TERRAFORM_DIR / "modules" / "github-oidc-deployer"
WORKFLOW = PROJECT.parent.parent / ".github" / "workflows" / "cloudfront-s3-static-delivery.yml"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
