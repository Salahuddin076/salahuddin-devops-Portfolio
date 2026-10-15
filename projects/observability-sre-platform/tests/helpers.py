"""Shared test setup: paths, and generator/ on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
GENERATOR_DIR = PROJECT / "generator"
DEMO_DIR = PROJECT / "local" / "demo-app"
SLO_DIR = PROJECT / "slo"
GENERATED = PROJECT / "generated"
CHART_DIR = PROJECT / "helm" / "observability-stack"
SAMPLE_CSV = PROJECT / "sample-data" / "checkout-api-availability-hourly.csv"
OTEL_CONFIG = CHART_DIR / "files" / "otel-collector.yaml"
LOCAL_ALERTMANAGER = PROJECT / "local" / "alertmanager" / "alertmanager.yml"
CRD_SCHEMA_LOCATION = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
                       "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")
PROMETHEUS_IMAGE = "prom/prometheus:v3.5.0"

for p in (GENERATOR_DIR, DEMO_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
