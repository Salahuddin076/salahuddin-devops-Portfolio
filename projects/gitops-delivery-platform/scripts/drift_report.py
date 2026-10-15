#!/usr/bin/env python3
"""Report drift between rendered desired manifests and a live export (stdlib only).

  drift_report.py --desired rendered.yaml --live live.json [--app applicationset.yaml] [--format json]

--desired is `helm template` output (multi-document YAML). --live is a
`kubectl get ... -o json` / `-o yaml` export: a List, a single object, or
multi-document YAML. Resources are matched by kind and name.

Like Argo CD's diff, only fields that git declares are compared, so values
the API server defaults are not drift. Two exceptions, because they are what
a hand edit usually adds: extra keys in any `labels` / `annotations` map, and
extra items in a list of named objects (an injected container), are reported.

Never compared (the ignoreDifferences that every app gets):
  status, metadata.managedFields, metadata.resourceVersion / uid /
  generation / creationTimestamp, the kubectl last-applied and Deployment
  revision annotations, and spec.replicas on any workload an HPA in the
  desired set scales. --app adds the jsonPointers from the ignoreDifferences
  of an Application or ApplicationSet template.

Exit status: 0 no drift, 1 drift, 2 usage or parse error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_lite  # noqa: E402

ALWAYS_IGNORED = [
    ("*", "/status"),
    ("*", "/metadata/managedFields"),
    ("*", "/metadata/resourceVersion"),
    ("*", "/metadata/uid"),
    ("*", "/metadata/generation"),
    ("*", "/metadata/creationTimestamp"),
    ("*", "/metadata/selfLink"),
    ("*", "/metadata/annotations/kubectl.kubernetes.io~1last-applied-configuration"),
    ("*", "/metadata/annotations/deployment.kubernetes.io~1revision"),
    ("*", "/metadata/annotations/rollout.argoproj.io~1revision"),
]
EXTRA_KEY_MAPS = ("labels", "annotations")


def load_docs(path: str) -> list[dict]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror}") from exc
    stripped = text.lstrip()
    docs = [json.loads(text)] if stripped.startswith(("{", "[")) else yaml_lite.load_all(text)
    out: list[dict] = []
    for d in docs:
        if isinstance(d, list):
            out.extend(d)
        elif isinstance(d, dict) and str(d.get("kind", "")).endswith("List") and isinstance(d.get("items"), list):
            out.extend(d["items"])
        elif isinstance(d, dict):
            out.append(d)
    for d in out:
        if not isinstance(d, dict) or "kind" not in d or "name" not in (d.get("metadata") or {}):
            raise ValueError(f"{path}: every object needs kind and metadata.name")
    return out


def key_of(obj: dict) -> str:
    return f"{obj['kind']}/{obj['metadata']['name']}"


def group_of(api_version: str) -> str:
    return api_version.split("/", 1)[0] if "/" in api_version else ""


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def hpa_targets(desired: list[dict]) -> set[str]:
    out = set()
    for d in desired:
        if d["kind"] == "HorizontalPodAutoscaler":
            ref = (d.get("spec") or {}).get("scaleTargetRef") or {}
            if ref.get("kind") and ref.get("name"):
                out.add(f"{ref['kind']}/{ref['name']}")
    return out


def app_ignores(path: str) -> list[tuple[str, str, str]]:
    """(group, kind, pointer) from an Application or ApplicationSet's ignoreDifferences."""
    out = []
    for doc in load_any(path):
        spec = doc.get("spec") or {}
        if doc.get("kind") == "ApplicationSet":
            spec = (spec.get("template") or {}).get("spec") or {}
        for rule in spec.get("ignoreDifferences") or []:
            for ptr in rule.get("jsonPointers") or []:
                out.append((rule.get("group", ""), rule.get("kind", "*"), ptr))
    return out


def load_any(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [d for d in yaml_lite.load_all(text) if isinstance(d, dict)]


def ignored_pointers(obj: dict, hpa: set[str], extra: list[tuple[str, str, str]]) -> list[str]:
    ptrs = [p for _, p in ALWAYS_IGNORED]
    if key_of(obj) in hpa:
        ptrs.append("/spec/replicas")
    grp = group_of(obj.get("apiVersion", ""))
    for g, kind, p in extra:
        if kind in ("*", obj["kind"]) and g in (grp, "*"):
            ptrs.append(p)
    return ptrs


METADATA_NOISE = {p for _, p in ALWAYS_IGNORED if p.startswith("/metadata/")}


def resolve(obj, ptr: str):
    """Follow a JSON pointer; return (found, value)."""
    cur = obj
    for raw in ptr.lstrip("/").split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return False, None
    return True, cur


def pointer_display(ptr: str) -> str:
    return _display([t.replace("~1", "/").replace("~0", "~") for t in ptr.lstrip("/").split("/")])


def ignored_present(desired: dict, live: dict, ignored: list[str]) -> list[str]:
    """Ignored fields (other than metadata bookkeeping) where live differs from git."""
    out = []
    for ptr in ignored:
        if ptr in METADATA_NOISE:
            continue
        found, value = resolve(live, ptr)
        if found and resolve(desired, ptr) != (True, value):
            out.append(pointer_display(ptr))
    return out


def _is_ignored(ptr: str, ignored: list[str]) -> bool:
    return any(ptr == i or ptr.startswith(i + "/") for i in ignored)


def _display(ptr_parts: list[str]) -> str:
    out = ""
    for part in ptr_parts:
        if part.startswith("["):
            out += part
        elif "." in part or "/" in part:
            out += f'["{part}"]'
        else:
            out += ("." if out else "") + part
    return out


def compare(desired, live, parts: list[str], ptr: str, ignored: list[str], findings: list, ignored_hits: list):
    if _is_ignored(ptr, ignored):
        if desired != live:
            ignored_hits.append(_display(parts))
        return
    if isinstance(desired, dict) and isinstance(live, dict):
        for k, v in desired.items():
            child_ptr = f"{ptr}/{escape(k)}"
            if k not in live:
                if not _is_ignored(child_ptr, ignored):
                    findings.append(("-", _display(parts + [k]), v, None))
                continue
            compare(v, live[k], parts + [k], child_ptr, ignored, findings, ignored_hits)
        if parts and parts[-1] in EXTRA_KEY_MAPS:
            for k, v in live.items():
                child_ptr = f"{ptr}/{escape(k)}"
                if k not in desired and not _is_ignored(child_ptr, ignored):
                    findings.append(("+", _display(parts + [k]), None, v))
        for k in EXTRA_KEY_MAPS:
            # a whole labels/annotations map that git doesn't declare: still report its keys
            if k not in desired and isinstance(live.get(k), dict):
                compare({}, live[k], parts + [k], f"{ptr}/{k}", ignored, findings, ignored_hits)
        return
    if isinstance(desired, list) and isinstance(live, list):
        named = all(isinstance(x, dict) and "name" in x for x in desired + live) and desired
        if named:
            live_by = {x["name"]: x for x in live}
            for i, item in enumerate(desired):
                label = f"[{item['name']}]"
                if item["name"] not in live_by:
                    findings.append(("-", _display(parts) + label, item, None))
                    continue
                live_idx = next(j for j, x in enumerate(live) if x["name"] == item["name"])
                compare(item, live_by[item["name"]], parts + [label], f"{ptr}/{live_idx}", ignored,
                        findings, ignored_hits)
            names = {x["name"] for x in desired}
            for x in live:
                if x["name"] not in names:
                    findings.append(("+", _display(parts) + f"[{x['name']}]", None, x))
            return
        if len(desired) == len(live) and all(isinstance(x, (dict, list)) for x in desired):
            for i, (d, lv) in enumerate(zip(desired, live)):
                compare(d, lv, parts + [f"[{i}]"], f"{ptr}/{i}", ignored, findings, ignored_hits)
            return
    if not _equal(desired, live):
        findings.append(("~", _display(parts), desired, live))


def _equal(a, b) -> bool:
    if a == b:
        return True
    # helm renders some numbers as strings and the API server as ints (and the reverse)
    if isinstance(a, (int, str)) and isinstance(b, (int, str)) and not isinstance(a, bool) and not isinstance(b, bool):
        return str(a) == str(b)
    return False


def report(desired: list[dict], live: list[dict], extra_ignores=None) -> dict:
    extra_ignores = extra_ignores or []
    hpa = hpa_targets(desired)
    live_by = {key_of(o): o for o in live}
    desired_keys = {key_of(o) for o in desired}
    resources = []
    for obj in desired:
        k = key_of(obj)
        if k not in live_by:
            resources.append({"resource": k, "state": "missing", "fields": [], "ignored": []})
            continue
        findings: list = []
        ignored_hits: list = []
        ignored = ignored_pointers(obj, hpa, extra_ignores)
        compare(obj, live_by[k], [], "", ignored, findings, ignored_hits)
        ignored_hits += ignored_present(obj, live_by[k], ignored)
        resources.append({
            "resource": k,
            "state": "drift" if findings else "in-sync",
            "fields": [{"op": op, "path": p, "desired": d, "live": lv} for op, p, d, lv in findings],
            "ignored": sorted(set(ignored_hits)),
        })
    for obj in live:
        if key_of(obj) not in desired_keys:
            resources.append({"resource": key_of(obj), "state": "extra", "fields": [], "ignored": []})
    drifted = [r for r in resources if r["state"] != "in-sync"]
    return {
        "resources": resources,
        "summary": {
            "desired": len(desired), "live": len(live),
            "drifted": len(drifted),
            "fields": sum(len(r["fields"]) for r in resources),
            "ignored": sum(len(r["ignored"]) for r in resources),
            "hpa_managed": sorted(hpa),
        },
    }


def _fmt(v) -> str:
    return json.dumps(v, sort_keys=True) if not isinstance(v, str) else json.dumps(v)


def render_text(rep: dict) -> str:
    s = rep["summary"]
    lines = [f"drift report: {s['desired']} desired resource(s), {s['live']} live",
             "ignored everywhere: status, and metadata bookkeeping (managedFields, resourceVersion, uid, "
             "generation, creationTimestamp, last-applied and revision annotations)"]
    if s["hpa_managed"]:
        lines.append(f"ignored on HPA targets: spec.replicas ({', '.join(s['hpa_managed'])})")
    for r in rep["resources"]:
        if r["state"] == "missing":
            lines.append(f"{r['resource']}: MISSING (in git, not in the cluster)")
        elif r["state"] == "extra":
            lines.append(f"{r['resource']}: EXTRA (in the cluster, not in git; prune would delete it)")
        elif r["state"] == "drift":
            lines.append(f"{r['resource']}: DRIFT")
        else:
            lines.append(f"{r['resource']}: in sync" + (f" (ignored: {', '.join(r['ignored'])})" if r["ignored"] else ""))
        for f in r["fields"]:
            if f["op"] == "~":
                lines.append(f"  ~ {f['path']}: desired {_fmt(f['desired'])}, live {_fmt(f['live'])}")
            elif f["op"] == "+":
                lines.append(f"  + {f['path']}: {_fmt(f['live'])} (live only)")
            else:
                lines.append(f"  - {f['path']}: {_fmt(f['desired'])} (missing in live)")
        if r["state"] == "drift" and r["ignored"]:
            lines.append(f"  (ignored: {', '.join(r['ignored'])})")
    verdict = "DRIFT" if s["drifted"] else "no drift"
    lines.append(f"summary: {verdict}: {s['drifted']} of {len(rep['resources'])} resource(s) differ, "
                 f"{s['fields']} field(s); {s['ignored']} ignored difference(s)")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="drift_report.py", description="Desired vs live drift, Argo CD style.")
    p.add_argument("--desired", required=True, help="rendered manifests (YAML), or - for stdin")
    p.add_argument("--live", required=True, help="kubectl export (JSON or YAML)")
    p.add_argument("--app", help="Application/ApplicationSet whose ignoreDifferences to apply as well")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)
    try:
        desired = load_docs(args.desired)
        live = load_docs(args.live)
        extra = app_ignores(args.app) if args.app else []
    except (ValueError, OSError) as exc:
        print(f"drift_report: error: {exc}", file=sys.stderr)
        return 2
    rep = report(desired, live, extra)
    print(json.dumps(rep, indent=2, sort_keys=True) if args.format == "json" else render_text(rep))
    return 1 if rep["summary"]["drifted"] else 0


if __name__ == "__main__":
    sys.exit(main())
