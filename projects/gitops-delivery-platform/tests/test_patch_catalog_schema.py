"""patch_catalog_schema.py repairs the catalog's stray boolean property schemas, offline."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES

import patch_catalog_schema as pcs

FIXTURE = FIXTURES / "catalog" / "external-secrets.io" / "clustersecretstore_v1.json"


class RepairTests(unittest.TestCase):
    def test_removes_only_the_stray_entry(self):
        fixed, removed = pcs.repair(json.loads(FIXTURE.read_text()))
        self.assertEqual(removed, 1)
        item = fixed["properties"]["spec"]["properties"]["rules"]["items"]
        self.assertEqual(sorted(item["properties"]), ["name", "properties"])
        # real additionalProperties: false keywords (outside `properties` maps) are kept
        self.assertIs(item["additionalProperties"], False)
        self.assertIs(fixed["properties"]["spec"]["additionalProperties"], False)

    def test_clean_schema_is_unchanged(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
        self.assertEqual(pcs.repair(schema), (schema, 0))

    def test_cli_with_a_local_catalog(self):
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = pcs.main(["--out", out, "--catalog", str(FIXTURES / "catalog"),
                           "external-secrets.io/clustersecretstore_v1"])
            self.assertEqual(rc, 0)
            written = json.loads((Path(out) / "external-secrets.io" / "clustersecretstore_v1.json").read_text())
            self.assertEqual(pcs.repair(written)[1], 0)
            self.assertEqual(pcs.main(["--out", out, "--catalog", str(FIXTURES / "catalog"), "nope/missing_v1"]), 2)


if __name__ == "__main__":
    unittest.main()
