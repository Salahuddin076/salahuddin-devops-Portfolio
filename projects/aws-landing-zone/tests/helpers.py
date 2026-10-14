"""Shared test helpers: import paths and small builders for SCP fixtures."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
POLICY_DIR = PROJECT / "policy"
FIXTURES = POLICY_DIR / "fixtures"
BAD_SCPS = FIXTURES / "scp-bad"
SCP_DIR = PROJECT / "terraform" / "modules" / "guardrails" / "policies" / "scp"
TERRAFORM = PROJECT / "terraform"

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))


def scp(*statements: dict, version: str = "2012-10-17") -> dict:
    return {"Version": version, "Statement": list(statements)}


def deny(sid: str, action, **extra) -> dict:
    return {"Sid": sid, "Effect": "Deny", "Action": action, "Resource": "*", **extra}


class PolicyDir:
    """A temporary SCP directory: ``with PolicyDir({"name": doc}) as d:``.

    Values may be dicts (written as JSON) or strings (written verbatim, for
    invalid JSON and templates; a name ending in .tftpl keeps its suffix).
    """

    def __init__(self, files: dict[str, object], attachments: dict | None = None):
        self.files = files
        self.attachments = attachments

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for name, content in self.files.items():
            filename = name if name.endswith((".json", ".tftpl")) else f"{name}.json"
            text = content if isinstance(content, str) else json.dumps(content, indent=2)
            (root / filename).write_text(text)
        if self.attachments is not None:
            (root / "attachments.json").write_text(json.dumps(self.attachments))
        return root

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()
