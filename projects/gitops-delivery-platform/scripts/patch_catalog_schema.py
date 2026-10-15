#!/usr/bin/env python3
"""Fetch CRD schemas from the datree CRDs-catalog and repair one known converter defect (stdlib only).

  patch_catalog_schema.py --out DIR external-secrets.io/clustersecretstore_v1 [...]

Why: the catalog's external-secrets.io v1 SecretStore/ClusterSecretStore
schemas contain a field that is literally named `properties` (the CRD
provider's whitelist rules). The converter then writes a stray
`"additionalProperties": false` *inside* a `properties` map, i.e. as a
property whose schema is the boolean `false`. kubeconform v0.8.0 cannot
compile that schema and reports "could not find schema", so the resource
would never be validated.

The repair drops boolean-valued entries from every `properties` map. That
loosens exactly one spot (the unused CRD provider's whitelist rule) and keeps
every other constraint, including -strict additionalProperties elsewhere.
The result is written as DIR/<group>/<kind>_<version>.json, so pass
`-schema-location 'DIR/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'`
to kubeconform before the catalog location.

Exit status: 0 written, 2 fetch or parse error.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

CATALOG = "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main"


def repair(schema):
    """Return (fixed schema, number of stray boolean property entries removed)."""
    removed = 0

    def walk(node):
        nonlocal removed
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    kept = {}
                    for name, sub in value.items():
                        if isinstance(sub, bool):
                            removed += 1
                            continue
                        kept[name] = walk(sub)
                    out[key] = kept
                else:
                    out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema), removed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="patch_catalog_schema.py", description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True, help="directory for the repaired schemas")
    p.add_argument("--catalog", default=CATALOG, help="catalog base URL (or a local directory)")
    p.add_argument("schemas", nargs="+", help="<group>/<kind>_<version>, e.g. external-secrets.io/clustersecretstore_v1")
    args = p.parse_args(argv)
    for name in args.schemas:
        src = f"{args.catalog.rstrip('/')}/{name}.json"
        try:
            if "://" in src:
                with urllib.request.urlopen(src, timeout=60) as r:  # noqa: S310 (fixed https catalog URL)
                    raw = r.read()
            else:
                raw = Path(src).read_bytes()
            schema = json.loads(raw)
        except (OSError, ValueError) as exc:
            print(f"patch_catalog_schema: cannot load {src}: {exc}", file=sys.stderr)
            return 2
        fixed, removed = repair(schema)
        dest = args.out / f"{name}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(fixed), encoding="utf-8")
        print(f"{name}: removed {removed} stray boolean property schema(s) -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
