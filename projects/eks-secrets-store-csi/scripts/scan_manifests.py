#!/usr/bin/env python3
"""Policy check over rendered Kubernetes manifests: no secret reaches the cluster as plain config.

Usage:
  helm template secure-frontend helm/secure-frontend | scan_manifests.py -
  scan_manifests.py FILE [FILE ...] [--fail-on error|warning] [--format text|json]

Rules (ID, severity):
  SM001 error    env[].value under a secret-looking name (DB_PASSWORD, API_KEY, *_TOKEN ...).
                 Names that point at a secret (`*_FILE`, `*_PATH`, `*_DIR`, `*_ARN` ...) are fine.
  SM002 error    env[].value whose *value* looks like a credential (AKIA..., a private
                 key header, a high-entropy token), whatever the name.
  SM003 error    a `Secret` object with literal `data` / `stringData`. Secret values come
                 from Secrets Manager through the CSI driver, never from the chart.
  SM004 error    a Secrets Store CSI volume (driver secrets-store.csi.k8s.io) without
                 `csi.readOnly: true`, or a container mounting it without `readOnly: true`.
  SM005 error    a ServiceAccount, or a pod using it, with automountServiceAccountToken not
                 false. Neither the app nor the CSI/ASCP path needs the kube-API token:
                 the driver gets a pod token from kubelet (CSIDriver tokenRequests), and EKS
                 Pod Identity injects its own projected token separately. Opt out per object
                 with the annotation `secrets.example.com/kube-api-token-justification`.
  SM006 warning a secret consumed as an env var (`env[].valueFrom.secretKeyRef` or
                 `envFrom[].secretRef`). Env vars leak into crash dumps, `/proc/<pid>/environ`
                 and child processes, and never pick up a rotation. Prefer the mounted files.
  SM007 warning a SecretProviderClass with `secretObjects`: the driver will copy the
                 values into a Kubernetes Secret, i.e. into etcd. Fine when deliberate.

Exit status: 0 when nothing at or above --fail-on, 1 otherwise, 2 on a usage or parse error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_lite  # noqa: E402
from secret_patterns import is_secret_name, looks_like_secret_value, mask  # noqa: E402

CSI_DRIVER = "secrets-store.csi.k8s.io"
JUSTIFICATION = "secrets.example.com/kube-api-token-justification"
SEVERITY = {"SM001": "error", "SM002": "error", "SM003": "error", "SM004": "error",
            "SM005": "error", "SM006": "warning", "SM007": "warning"}
ORDER = {"warning": 1, "error": 2}
POD_TEMPLATE_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job"}


@dataclass
class Finding:
    rule: str
    source: str
    obj: str
    message: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.rule]

    def text(self) -> str:
        return f"{self.source} {self.obj}: {self.severity.upper()} {self.rule} {self.message}"


def _meta(doc: dict) -> dict:
    return doc.get("metadata") or {}


def obj_id(doc: dict) -> str:
    meta = _meta(doc)
    ns = f"{meta['namespace']}/" if meta.get("namespace") else ""
    return f"{doc.get('kind', '?')}/{ns}{meta.get('name', '?')}"


def pod_spec(doc: dict) -> tuple[dict | None, dict]:
    """(pod spec, pod template metadata) for any workload kind."""
    kind, spec = doc.get("kind"), doc.get("spec") or {}
    if kind == "Pod":
        return spec, _meta(doc)
    if kind == "CronJob":
        spec = ((spec.get("jobTemplate") or {}).get("spec") or {})
    if kind in POD_TEMPLATE_KINDS or kind == "CronJob":
        tmpl = spec.get("template") or {}
        return tmpl.get("spec") or {}, tmpl.get("metadata") or {}
    return None, {}


def _justified(*metas: dict) -> bool:
    return any(str((m.get("annotations") or {}).get(JUSTIFICATION, "")).strip() for m in metas)


def check_containers(pod: dict, src: str, oid: str) -> list[Finding]:
    out = []
    csi_volumes = {v["name"] for v in pod.get("volumes") or []
                   if (v.get("csi") or {}).get("driver") == CSI_DRIVER}
    for v in pod.get("volumes") or []:
        csi = v.get("csi") or {}
        if csi.get("driver") == CSI_DRIVER and csi.get("readOnly") is not True:
            out.append(Finding("SM004", src, oid, f"CSI volume `{v['name']}` is not `readOnly: true`"))
    containers = (pod.get("initContainers") or []) + (pod.get("containers") or [])
    for c in containers:
        cname = c.get("name", "?")
        for e in c.get("env") or []:
            name = str(e.get("name", ""))
            if "value" in e and e["value"] not in (None, ""):
                value = str(e["value"])
                if is_secret_name(name):
                    out.append(Finding("SM001", src, oid,
                                       f"container `{cname}` env `{name}` has a literal value ({mask(value)})"))
                else:
                    reason = looks_like_secret_value(value)
                    if reason:
                        out.append(Finding("SM002", src, oid,
                                           f"container `{cname}` env `{name}` value looks like a credential ({reason}, {mask(value)})"))
            ref = (e.get("valueFrom") or {}).get("secretKeyRef")
            if ref:
                out.append(Finding("SM006", src, oid,
                                   f"container `{cname}` env `{name}` reads Secret `{ref.get('name')}`; mount files instead"))
        for ef in c.get("envFrom") or []:
            if ef.get("secretRef"):
                out.append(Finding("SM006", src, oid,
                                   f"container `{cname}` envFrom Secret `{ef['secretRef'].get('name')}`; mount files instead"))
        for m in c.get("volumeMounts") or []:
            if m.get("name") in csi_volumes and m.get("readOnly") is not True:
                out.append(Finding("SM004", src, oid,
                                   f"container `{cname}` mounts CSI volume `{m['name']}` without `readOnly: true`"))
    return out


def scan_docs(docs: list, src: str) -> list[Finding]:
    out: list[Finding] = []
    service_accounts = {}
    pods = []
    for doc in docs:
        if not isinstance(doc, dict) or "kind" not in doc:
            continue
        kind, oid = doc["kind"], obj_id(doc)
        if kind == "List":
            out.extend(scan_docs(doc.get("items") or [], src))
            continue
        if kind == "Secret":
            literal = [k for k in ("data", "stringData") if doc.get(k)]
            if literal:
                out.append(Finding("SM003", src, oid, f"Secret with literal {' and '.join(literal)} "
                                                      f"(keys: {', '.join(sorted(set().union(*(doc[k] for k in literal))))})"))
        elif kind == "ServiceAccount":
            service_accounts[_meta(doc).get("name")] = doc
            if doc.get("automountServiceAccountToken") is not False and not _justified(_meta(doc)):
                out.append(Finding("SM005", src, oid, "automountServiceAccountToken is not false"))
        elif kind == "SecretProviderClass" and (doc.get("spec") or {}).get("secretObjects"):
            names = [s.get("secretName") for s in doc["spec"]["secretObjects"]]
            out.append(Finding("SM007", src, oid, f"secretObjects syncs into Kubernetes Secret(s) {', '.join(map(str, names))} (stored in etcd)"))
        pod, tmeta = pod_spec(doc)
        if pod is not None:
            pods.append((doc, pod, tmeta))
            out.extend(check_containers(pod, src, oid))
    for doc, pod, tmeta in pods:
        sa_name = pod.get("serviceAccountName") or "default"
        sa = service_accounts.get(sa_name)
        automount = pod.get("automountServiceAccountToken")
        # The pod field wins over the ServiceAccount's; unset inherits it (and an
        # unrendered SA defaults to true).
        effective = automount if automount is not None else (sa or {}).get("automountServiceAccountToken", True)
        if effective is not False and not _justified(_meta(doc), tmeta):
            out.append(Finding("SM005", src, obj_id(doc),
                               f"pod mounts the kube-API token (automountServiceAccountToken {effective!r}, "
                               f"ServiceAccount `{sa_name}`)"))
    return out


def scan_text(text: str, src: str) -> list[Finding]:
    return scan_docs(yaml_lite.load_all(text), src)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("paths", nargs="+", help="manifest files, or - for stdin")
    p.add_argument("--fail-on", choices=("error", "warning"), default="error")
    p.add_argument("--format", choices=("text", "json"), default="text")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    findings, objects = [], 0
    for path in args.paths:
        try:
            text = sys.stdin.read() if path == "-" else Path(path).read_text()
            docs = yaml_lite.load_all(text)
        except (OSError, ValueError) as exc:
            print(f"scan_manifests: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        src = "<stdin>" if path == "-" else path
        objects += sum(1 for d in docs if isinstance(d, dict) and "kind" in d)
        findings.extend(scan_docs(docs, src))
    errors = sum(f.severity == "error" for f in findings)
    warnings = len(findings) - errors
    if args.format == "json":
        print(json.dumps({"objects": objects, "errors": errors, "warnings": warnings,
                          "findings": [dict(asdict(f), severity=f.severity) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f.text())
        print(f"scan_manifests: {objects} objects, {errors} error(s), {warnings} warning(s)")
    threshold = ORDER[args.fail_on]
    return 1 if any(ORDER[f.severity] >= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
