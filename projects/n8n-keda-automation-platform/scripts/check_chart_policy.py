#!/usr/bin/env python3
"""Policy checks for rendered n8n queue-mode manifests (stdlib only).

Usage:
  helm template n8n helm/n8n-platform | check_chart_policy.py - [options]
  check_chart_policy.py FILE [FILE ...] [--format text|json] [--fail-on error|warning]

Rules (ID, severity):
  CP001 error    worker terminationGracePeriodSeconds < the max execution time
                 (scale-in would SIGKILL a run that is allowed to finish)
  CP002 error    worker grace period does not cover preStop + N8N_GRACEFUL_SHUTDOWN_TIMEOUT,
                 or that timeout is below the max execution time
  CP003 error    main Deployment replicas != 1 (single-main: schedules would fire twice)
  CP004 warning  main Deployment strategy is not Recreate (two mains overlap during a rollout)
  CP005 error    ScaledObject minReplicaCount 0 with cooldownPeriod below --min-cooldown
  CP006 error    env var with a literal secret value (secret-like name without _FILE, or a
                 credential-looking value)
  CP007 error    N8N_ENCRYPTION_KEY set as a literal value
  CP008 error    n8n container with no encryption key from a file or a Secret
                 (each pod would generate its own key and could not decrypt credentials)
  CP009 error    ScaledObject redis trigger on a list that is not <bull prefix>:jobs:wait|active
  CP010 error    n8n container not in queue mode (EXECUTIONS_MODE != queue)

The max execution time comes from --max-execution-seconds, else from the
worker's `n8n.example.com/max-execution-seconds` annotation, else from its
EXECUTIONS_TIMEOUT env var. Exit 0 when nothing at or above --fail-on, 1
otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_lite  # noqa: E402

MAX_EXEC_ANNOTATION = "n8n.example.com/max-execution-seconds"
SECRET_NAME = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|PRIVATE_KEY|API_KEY|ENCRYPTION_KEY|AUTH)", re.I)
CREDENTIAL_VALUE = [
    ("AWS access key ID", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("URL with embedded password", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
SEVERITY = {"error": 2, "warning": 1}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


@dataclass
class Finding:
    source: str
    obj: str
    rule: str
    severity: str
    message: str

    def text(self) -> str:
        return f"{self.source} {self.obj}: {self.severity.upper()} {self.rule} {self.message}"


def _obj_id(doc: dict) -> str:
    meta = doc.get("metadata") or {}
    return f"{doc.get('kind')}/{meta.get('namespace', '-')}/{meta.get('name', '?')}"


def _pod_spec(doc: dict) -> dict | None:
    kind = doc.get("kind")
    if kind not in WORKLOAD_KINDS:
        return None
    spec = doc.get("spec") or {}
    if kind == "CronJob":
        spec = ((spec.get("jobTemplate") or {}).get("spec")) or {}
    return ((spec.get("template") or {}).get("spec")) or {}


def _is_n8n(container: dict) -> bool:
    image = str(container.get("image", ""))
    return "n8n" in image.split("/")[-1].split(":")[0]


def _role(container: dict) -> str:
    args = container.get("args") or container.get("command") or []
    first = str(args[0]) if args else "start"
    return first if first in ("start", "webhook", "worker") else "start"


def _env(container: dict) -> dict[str, dict]:
    return {e.get("name"): e for e in container.get("env") or [] if isinstance(e, dict)}


def _mask(value: str) -> str:
    return f"{value[:4]}...<{len(value)} chars>" if len(value) > 4 else "<redacted>"


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def check_docs(docs: list, source: str, *, max_execution_seconds: int | None = None,
               min_cooldown: int = 120, bull_prefix: str = "bull") -> list[Finding]:
    out: list[Finding] = []

    def add(doc, rule, severity, msg):
        out.append(Finding(source, _obj_id(doc), rule, severity, msg))

    expanded = []
    for d in docs:
        if isinstance(d, dict) and d.get("kind") == "List":
            expanded.extend(d.get("items") or [])
        elif isinstance(d, dict):
            expanded.append(d)

    for doc in expanded:
        pod = _pod_spec(doc)
        if pod is not None:
            containers = [c for c in pod.get("containers") or [] if isinstance(c, dict)]
            n8n = [c for c in containers if _is_n8n(c)]
            for c in containers:
                for name, e in _env(c).items():
                    if "value" not in e or e.get("value") in (None, ""):
                        continue
                    value = str(e["value"])
                    if name == "N8N_ENCRYPTION_KEY":
                        add(doc, "CP007", "error", f"container `{c.get('name')}` sets N8N_ENCRYPTION_KEY "
                            f"literally ({_mask(value)}); use N8N_ENCRYPTION_KEY_FILE or a secretKeyRef")
                        continue
                    if SECRET_NAME.search(name) and not name.endswith("_FILE") \
                            and value.lower() not in ("true", "false"):
                        add(doc, "CP006", "error",
                            f"container `{c.get('name')}` env `{name}` has a literal value ({_mask(value)})")
                        continue
                    for label, rx in CREDENTIAL_VALUE:
                        if rx.search(value):
                            add(doc, "CP006", "error", f"container `{c.get('name')}` env `{name}` value "
                                f"looks like a credential ({label}, {_mask(value)})")
                            break
            for c in n8n:
                env = _env(c)
                key_file = env.get("N8N_ENCRYPTION_KEY_FILE", {}).get("value")
                key_ref = (env.get("N8N_ENCRYPTION_KEY", {}).get("valueFrom") or {}).get("secretKeyRef")
                literal = "value" in env.get("N8N_ENCRYPTION_KEY", {})
                if not (key_file or key_ref or literal):
                    add(doc, "CP008", "error", f"n8n container `{c.get('name')}` has no encryption key "
                        "(N8N_ENCRYPTION_KEY_FILE or N8N_ENCRYPTION_KEY from a secretKeyRef)")
                mode = env.get("EXECUTIONS_MODE", {}).get("value")
                if mode != "queue":
                    add(doc, "CP010", "error", f"n8n container `{c.get('name')}` EXECUTIONS_MODE is "
                        f"{mode!r}, not 'queue'")

            roles = {_role(c) for c in n8n}
            if doc.get("kind") == "Deployment" and "worker" in roles:
                c = next(c for c in n8n if _role(c) == "worker")
                env = _env(c)
                limit = max_execution_seconds
                if limit is None:
                    limit = _int(((doc.get("metadata") or {}).get("annotations") or {}).get(MAX_EXEC_ANNOTATION))
                if limit is None:
                    limit = _int(env.get("EXECUTIONS_TIMEOUT", {}).get("value"))
                grace = _int(pod.get("terminationGracePeriodSeconds"), 30)
                if limit is None or limit <= 0:
                    add(doc, "CP001", "error", "no max execution time: set EXECUTIONS_TIMEOUT or the "
                        f"{MAX_EXEC_ANNOTATION} annotation")
                elif grace < limit:
                    add(doc, "CP001", "error", f"terminationGracePeriodSeconds {grace} < max execution "
                        f"time {limit}s: scale-in would kill running executions")
                shutdown = _int(env.get("N8N_GRACEFUL_SHUTDOWN_TIMEOUT", {}).get("value"), 30)
                pre = (((c.get("lifecycle") or {}).get("preStop") or {}).get("sleep") or {}).get("seconds", 0)
                pre = _int(pre, 0)
                if limit and shutdown < limit:
                    add(doc, "CP002", "error", f"N8N_GRACEFUL_SHUTDOWN_TIMEOUT {shutdown}s < max execution "
                        f"time {limit}s: n8n force-exits before the run ends")
                if grace < pre + shutdown:
                    add(doc, "CP002", "error", f"terminationGracePeriodSeconds {grace} < preStop {pre}s + "
                        f"N8N_GRACEFUL_SHUTDOWN_TIMEOUT {shutdown}s: SIGKILL lands mid-drain")
            if doc.get("kind") == "Deployment" and "start" in roles and n8n:
                spec = doc.get("spec") or {}
                replicas = spec.get("replicas", 1)
                if replicas != 1:
                    add(doc, "CP003", "error", f"main replicas is {replicas}; single-main mode needs exactly 1")
                strategy = (spec.get("strategy") or {}).get("type", "RollingUpdate")
                if strategy != "Recreate":
                    add(doc, "CP004", "warning", f"main strategy is {strategy}; Recreate keeps two mains "
                        "from overlapping")

        if doc.get("kind") == "ScaledObject":
            spec = doc.get("spec") or {}
            min_rc = _int(spec.get("minReplicaCount"), 0)
            cooldown = _int(spec.get("cooldownPeriod"), 300)
            if min_rc == 0 and cooldown < min_cooldown:
                add(doc, "CP005", "error", f"minReplicaCount 0 with cooldownPeriod {cooldown}s < {min_cooldown}s: "
                    "workers would flap to zero between bursts")
            allowed = {f"{bull_prefix}:jobs:wait", f"{bull_prefix}:jobs:active"}
            for trig in spec.get("triggers") or []:
                if trig.get("type") != "redis":
                    continue
                list_name = (trig.get("metadata") or {}).get("listName")
                if list_name not in allowed:
                    add(doc, "CP009", "error", f"redis trigger `{trig.get('name', '?')}` watches {list_name!r}; "
                        f"n8n's Bull lists are {sorted(allowed)}")
    return out


def check_text(text: str, source: str, **kw) -> list[Finding]:
    return check_docs(yaml_lite.load_all(text), source, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Policy checks for rendered n8n queue-mode manifests.")
    ap.add_argument("paths", nargs="+", help="manifest files, or - for stdin")
    ap.add_argument("--max-execution-seconds", type=int)
    ap.add_argument("--min-cooldown", type=int, default=120,
                    help="lowest cooldownPeriod allowed with minReplicaCount 0 (default 120)")
    ap.add_argument("--bull-prefix", default="bull")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--fail-on", choices=("error", "warning"), default="error")
    args = ap.parse_args(argv)

    findings, objects = [], 0
    for p in args.paths:
        try:
            text = sys.stdin.read() if p == "-" else Path(p).read_text()
            docs = yaml_lite.load_all(text)
        except (OSError, ValueError) as exc:
            print(f"check_chart_policy: error: {p}: {exc}", file=sys.stderr)
            return 2
        objects += sum(len(d.get("items") or []) if d.get("kind") == "List" else 1 for d in docs if isinstance(d, dict))
        findings += check_docs(docs, "stdin" if p == "-" else p, max_execution_seconds=args.max_execution_seconds,
                               min_cooldown=args.min_cooldown, bull_prefix=args.bull_prefix)

    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    if args.format == "json":
        print(json.dumps({"objects": objects, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f.text())
        print(f"check_chart_policy: {objects} objects, {errors} error(s), {warnings} warning(s)")
    threshold = SEVERITY[args.fail_on]
    return 1 if any(SEVERITY[f.severity] >= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
