"""Shared test helpers: import paths and a tiny plan-JSON builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
POLICY_DIR = PROJECT / "policy"
SCRIPTS_DIR = PROJECT / "scripts"
FIXTURES = POLICY_DIR / "fixtures"
SAMPLE_LOGS = PROJECT / "sample-data" / "waf-logs.jsonl"

for p in (POLICY_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def change(address: str, after: dict | None, actions=("create",)) -> dict:
    """One resource_changes entry in `terraform show -json` shape."""
    rtype, name = address.split(".")[-2], address.split(".")[-1].split("[")[0]
    return {
        "address": address,
        "mode": "managed",
        "type": rtype,
        "name": name,
        "provider_name": "registry.terraform.io/hashicorp/aws",
        "change": {"actions": list(actions), "before": None, "after": after, "after_unknown": {}},
    }


def plan(*changes: dict, configuration: dict | None = None) -> dict:
    p = {"format_version": "1.2", "terraform_version": "1.14.8", "resource_changes": list(changes)}
    if configuration is not None:
        p["configuration"] = {"root_module": configuration}
    return p


def policy_json(*statements: dict) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


GOOD_PAB = {"block_public_acls": True, "block_public_policy": True, "ignore_public_acls": True, "restrict_public_buckets": True}
