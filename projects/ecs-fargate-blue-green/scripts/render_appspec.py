#!/usr/bin/env python3
"""Render deploy/appspec.template.yaml and deploy/taskdef.template.json.

Inputs come from a JSON values file (`--values`) plus `--set KEY=VALUE`
overrides. Every placeholder used by a template must have a value, every
value is validated, and the image must carry an immutable tag or digest:
`latest`, or no tag at all, is refused. IMAGE_TAG is derived from IMAGE,
never supplied by hand, so the tag the hooks check is the tag ECS pulls.

The usual flow (docs/operations.md):
  1. render the task definition:  --only taskdef
  2. aws ecs register-task-definition --cli-input-json file://build/taskdef.json
  3. render the appspec with the new ARN:  --only appspec --set TASK_DEFINITION_ARN=...
  4. aws deploy create-deployment with the rendered appspec

Exit codes: 0 rendered, 1 validation failed (nothing written), 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from string import Template

PROJECT = Path(__file__).resolve().parent.parent
APPSPEC_TEMPLATE = PROJECT / "deploy" / "appspec.template.yaml"
TASKDEF_TEMPLATE = PROJECT / "deploy" / "taskdef.template.json"

APPSPEC_KEYS = (
    "TASK_DEFINITION_ARN",
    "CONTAINER_NAME",
    "CONTAINER_PORT",
    "PLATFORM_VERSION",
    "BEFORE_ALLOW_TRAFFIC_HOOK_ARN",
    "AFTER_ALLOW_TRAFFIC_HOOK_ARN",
)
TASKDEF_KEYS = (
    "FAMILY",
    "IMAGE",
    "CONTAINER_NAME",
    "CONTAINER_PORT",
    "CPU",
    "MEMORY",
    "CPU_ARCHITECTURE",
    "EXECUTION_ROLE_ARN",
    "TASK_ROLE_ARN",
    "APP_ENV",
    "LOG_GROUP",
    "AWS_REGION",
    "DB_SECRET_ARN",
)
DERIVED_KEYS = ("IMAGE_TAG",)
# Placeholders whose JSON leaf must become a number, not a string.
INT_KEYS = {"CONTAINER_PORT"}

_PARTITION = r"aws(?:-cn|-us-gov)?"
_REGION = r"[a-z]{2}(?:-[a-z]+)+-\d"
VALIDATORS: dict[str, tuple[re.Pattern[str], str]] = {
    "TASK_DEFINITION_ARN": (
        re.compile(rf"^arn:{_PARTITION}:ecs:{_REGION}:\d{{12}}:task-definition/[A-Za-z0-9_-]{{1,255}}:\d+$"),
        "a task definition ARN with a revision (…:task-definition/family:N)",
    ),
    "CONTAINER_NAME": (re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$"), "letters, digits, '-' or '_'"),
    "PLATFORM_VERSION": (re.compile(r"^(LATEST|\d+\.\d+\.\d+)$"), "LATEST or a version such as 1.4.0"),
    "BEFORE_ALLOW_TRAFFIC_HOOK_ARN": (
        re.compile(rf"^arn:{_PARTITION}:lambda:{_REGION}:\d{{12}}:function:[A-Za-z0-9_-]{{1,64}}(:[A-Za-z0-9_$-]+)?$"),
        "a Lambda function ARN",
    ),
    "FAMILY": (re.compile(r"^[A-Za-z0-9_-]{1,255}$"), "letters, digits, '-' or '_' (max 255)"),
    "CPU_ARCHITECTURE": (re.compile(r"^(ARM64|X86_64)$"), "ARM64 or X86_64"),
    "EXECUTION_ROLE_ARN": (re.compile(rf"^arn:{_PARTITION}:iam::\d{{12}}:role/[\w+=,.@/-]+$"), "an IAM role ARN"),
    "APP_ENV": (re.compile(r"^[a-z][a-z0-9-]{0,31}$"), "lowercase name such as dev, staging or prod"),
    "LOG_GROUP": (re.compile(r"^[\w#/.-]{1,512}$"), "a CloudWatch Logs group name"),
    "AWS_REGION": (re.compile(rf"^{_REGION}$"), "a region such as us-east-1"),
    "DB_SECRET_ARN": (
        re.compile(rf"^arn:{_PARTITION}:secretsmanager:{_REGION}:\d{{12}}:secret:[\w/+=.@-]+$"),
        "a Secrets Manager secret ARN without a :json-key suffix (the template adds :password::)",
    ),
}
VALIDATORS["AFTER_ALLOW_TRAFFIC_HOOK_ARN"] = VALIDATORS["BEFORE_ALLOW_TRAFFIC_HOOK_ARN"]
VALIDATORS["TASK_ROLE_ARN"] = VALIDATORS["EXECUTION_ROLE_ARN"]

# Valid Fargate cpu -> memory (MiB) combinations.
FARGATE_SIZES = {
    256: {512, 1024, 2048},
    512: set(range(1024, 4097, 1024)),
    1024: set(range(2048, 8193, 1024)),
    2048: set(range(4096, 16385, 1024)),
    4096: set(range(8192, 30721, 1024)),
    8192: set(range(16384, 61441, 4096)),
    16384: set(range(32768, 122881, 8192)),
}

_IMAGE = re.compile(
    r"^(?P<repo>[a-z0-9]+(?:[._-][a-z0-9]+)*(?::\d+)?(?:/[a-z0-9]+(?:[._/-][a-z0-9]+)*)+|[a-z0-9]+(?:[._-][a-z0-9]+)*)"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?"
    r"(?:@(?P<digest>sha256:[a-f0-9]{64}))?$"
)


class RenderError(ValueError):
    """One or more inputs are missing or invalid."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def image_tag(image: str) -> str:
    """Return the immutable reference (tag, or digest when present). Raises on mutable or untagged."""
    match = _IMAGE.match(image or "")
    if not match:
        raise RenderError([f"IMAGE {image!r} is not a valid image reference"])
    tag, digest = match.group("tag"), match.group("digest")
    if tag and tag.lower() == "latest":
        raise RenderError([f"IMAGE {image!r} uses the mutable tag 'latest'; deploy an immutable tag (commit SHA)"])
    if digest:
        return digest
    if not tag:
        raise RenderError([f"IMAGE {image!r} has no tag, which means 'latest'; deploy an immutable tag (commit SHA)"])
    return tag


def validate(values: dict[str, str], required: tuple[str, ...]) -> list[str]:
    problems = []
    for key in required:
        value = values.get(key)
        if value is None or str(value).strip() == "":
            problems.append(f"{key} is required")
            continue
        value = str(value)
        if any(ch in value for ch in "\"\n\r\\"):
            problems.append(f"{key} contains a quote, backslash or newline")
            continue
        if key in VALIDATORS:
            pattern, hint = VALIDATORS[key]
            if not pattern.match(value):
                problems.append(f"{key} = {value!r} is invalid: expected {hint}")
        if key == "CONTAINER_PORT":
            if not value.isdigit() or not 1 <= int(value) <= 65535:
                problems.append(f"CONTAINER_PORT = {value!r} must be an integer between 1 and 65535")
        if key == "IMAGE":
            try:
                image_tag(value)
            except RenderError as exc:
                problems.extend(exc.problems)
    if "CPU" in required and "MEMORY" in required:
        cpu, memory = str(values.get("CPU", "")), str(values.get("MEMORY", ""))
        if not cpu.isdigit() or int(cpu) not in FARGATE_SIZES:
            problems.append(f"CPU = {cpu!r} is not a Fargate size ({', '.join(map(str, FARGATE_SIZES))})")
        elif not memory.isdigit() or int(memory) not in FARGATE_SIZES[int(cpu)]:
            problems.append(f"MEMORY = {memory!r} is not valid with CPU {cpu} on Fargate")
    return problems


def _placeholders(text: str) -> set[str]:
    return {m.group("named") or m.group("braced") for m in Template.pattern.finditer(text)
            if m.group("named") or m.group("braced")}


def render_appspec(values: dict[str, str], template: str | None = None) -> str:
    text = APPSPEC_TEMPLATE.read_text() if template is None else template
    missing = sorted(_placeholders(text) - set(values))
    if missing:
        raise RenderError([f"{k} is required by the appspec template" for k in missing])
    rendered = Template(text).substitute(values)
    problems = []
    for needed in ("version: 0.0", "Type: AWS::ECS::Service", "TaskDefinition:", "ContainerName:",
                   "ContainerPort:", "PlatformVersion:", "BeforeAllowTraffic:", "AfterAllowTraffic:"):
        if needed not in rendered:
            problems.append(f"rendered appspec lacks '{needed}'")
    if "${" in rendered:
        problems.append("rendered appspec still contains an unresolved placeholder")
    if problems:
        raise RenderError(problems)
    return rendered


def _fill(node: object, values: dict[str, str]) -> object:
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, values) for v in node]
    if isinstance(node, str):
        # A leaf that is exactly "${CONTAINER_PORT}" becomes a JSON number.
        whole = re.fullmatch(r"\$\{(\w+)\}", node)
        if whole and whole.group(1) in INT_KEYS:
            return int(values[whole.group(1)])
        return Template(node).substitute(values)
    return node


def render_taskdef(values: dict[str, str], template: str | None = None) -> dict:
    text = TASKDEF_TEMPLATE.read_text() if template is None else template
    missing = sorted(_placeholders(text) - set(values))
    if missing:
        raise RenderError([f"{k} is required by the taskdef template" for k in missing])
    data = json.loads(text)
    # Environment values must stay strings even when they hold a number.
    rendered = _fill(data, values)
    assert isinstance(rendered, dict)
    for container in rendered.get("containerDefinitions", []):
        for env in container.get("environment", []):
            env["value"] = str(env["value"])
    problems = []
    for key in ("family", "cpu", "memory", "executionRoleArn", "taskRoleArn", "containerDefinitions",
                "runtimePlatform"):
        if not rendered.get(key):
            problems.append(f"rendered taskdef lacks '{key}'")
    containers = rendered.get("containerDefinitions") or []
    names = [c.get("name") for c in containers]
    if values.get("CONTAINER_NAME") not in names:
        problems.append(f"no container named {values.get('CONTAINER_NAME')!r} in the taskdef")
    for c in containers:
        if not c.get("image"):
            problems.append(f"container {c.get('name')!r} has no image")
        else:
            try:
                image_tag(c["image"])
            except RenderError as exc:
                problems.extend(exc.problems)
    if "${" in json.dumps(rendered):
        problems.append("rendered taskdef still contains an unresolved placeholder")
    if problems:
        raise RenderError(problems)
    return rendered


def build_values(base: dict[str, object], overrides: list[str]) -> dict[str, str]:
    values = {str(k): str(v) for k, v in base.items()}
    for item in overrides:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise RenderError([f"--set expects KEY=VALUE, got {item!r}"])
        values[key.strip()] = value
    for key in DERIVED_KEYS:
        if key in values:
            raise RenderError([f"{key} is derived from IMAGE; do not set it"])
    if values.get("IMAGE"):
        try:
            values["IMAGE_TAG"] = image_tag(values["IMAGE"])
        except RenderError:
            pass  # reported by validate()
    return values


def render(values: dict[str, str], only: str | None = None) -> dict[str, str]:
    """Validate and render. Returns {filename: content}. Raises RenderError."""
    required: tuple[str, ...] = ()
    if only in (None, "appspec"):
        required += APPSPEC_KEYS
    if only in (None, "taskdef"):
        required += tuple(k for k in TASKDEF_KEYS if k not in required)
    problems = validate(values, required)
    if problems:
        raise RenderError(problems)
    out: dict[str, str] = {}
    if only in (None, "taskdef"):
        out["taskdef.json"] = json.dumps(render_taskdef(values), indent=2) + "\n"
    if only in (None, "appspec"):
        out["appspec.yaml"] = render_appspec(values)
    return out


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the CodeDeploy appspec and ECS task definition.")
    parser.add_argument("--values", help="JSON file of placeholder values")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override one value")
    parser.add_argument("--only", choices=("appspec", "taskdef"), help="render one file only")
    parser.add_argument("--out-dir", default="build", help="output directory (default: build)")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing files")
    args = parser.parse_args(argv)

    base: dict[str, object] = {}
    if args.values:
        try:
            loaded = json.loads(Path(args.values).read_text())
        except OSError as exc:
            print(f"error: cannot read {args.values}: {exc.strerror or exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: {args.values} is not valid JSON: line {exc.lineno}: {exc.msg}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print(f"error: {args.values} must contain a JSON object", file=sys.stderr)
            return 2
        base = loaded

    try:
        values = build_values(base, args.set)
        files = render(values, args.only)
    except RenderError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    if args.stdout:
        for name, content in files.items():
            print(f"--- {name}")
            print(content.rstrip())
        return 0
    out_dir = Path(args.out_dir)
    try:
        for name, content in files.items():
            _atomic_write(out_dir / name, content)
    except OSError as exc:
        print(f"error: cannot write to {out_dir}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    for name in files:
        print(f"wrote {out_dir / name}")
    if "taskdef.json" in files:
        print(f"image tag: {values['IMAGE_TAG']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
