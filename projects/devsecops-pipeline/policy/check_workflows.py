#!/usr/bin/env python3
"""GitHub Actions workflow hardening linter (stdlib only).

Usage:
  check_workflows.py [PATH ...] [--format text|sarif] [--output FILE]
                     [--fail-on error|warning] [--uri-base DIR]

PATH is a workflow file or a directory (every *.yml / *.yaml directly in
it). With no PATH it scans `.github/workflows` under the current directory.
The tool only reads files.

Rules (ID, default severity):
  WF000 error    file cannot be parsed by the YAML-subset reader
  WF001 error    no top-level `permissions` block
  WF002 error    `permissions: write-all` (top level or job level)
  WF010 error    third-party action / reusable workflow not pinned to a 40-char commit SHA
  WF011 warning  first-party (actions/*, github/*) action pinned to a tag, not a SHA
  WF012 warning  `docker://` action without an `@sha256:` digest
  WF013 warning  SHA pin without a `# vX.Y.Z` comment saying which release it is
  WF020 error    `pull_request_target` workflow checks out the PR head
  WF030 error    user-controlled `github.event.*` / `github.head_ref` expanded inside `run:`
                 (or `actions/github-script` `script:`): script injection
  WF040 error    `id-token: write` granted at the top level instead of per job
  WF050 error    `actions/checkout` without `persist-credentials: false` in a job that does not push

Exit status: 0 when nothing at or above --fail-on severity, 1 otherwise,
2 on usage errors (unreadable path).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yaml_subset import YList, YMap, YamlSubsetError, parse  # noqa: E402

TOOL_NAME = "check-workflows"
TOOL_VERSION = "1.0.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SEVERITY_ORDER = {"note": 0, "warning": 1, "error": 2}

RULES: dict[str, tuple[str, str, str]] = {
    # id: (severity, short name, help text)
    "WF000": ("error", "parse-error", "The workflow could not be parsed; the other rules did not run on it."),
    "WF001": ("error", "missing-top-level-permissions",
              "Declare a top-level `permissions:` block (for example `contents: read`) so the GITHUB_TOKEN "
              "does not fall back to the repository default, which may be read/write."),
    "WF002": ("error", "write-all-permissions",
              "`write-all` grants every scope. List only the scopes the job needs."),
    "WF010": ("error", "third-party-action-not-sha-pinned",
              "Pin third-party actions to a full 40-character commit SHA with a `# vX.Y.Z` comment. "
              "A tag can be moved to malicious code by anyone who controls the upstream repository."),
    "WF011": ("warning", "first-party-action-not-sha-pinned",
              "First-party actions (actions/*, github/*) are lower risk but still mutable at a tag; "
              "prefer a SHA pin and let Dependabot bump it."),
    "WF012": ("warning", "docker-action-not-digest-pinned",
              "Pin `docker://` actions by `@sha256:` digest; image tags are mutable."),
    "WF013": ("warning", "sha-pin-without-version-comment",
              "Add a `# vX.Y.Z` comment after a SHA pin so reviewers and Dependabot know the release."),
    "WF020": ("error", "pull-request-target-checks-out-head",
              "`pull_request_target` runs with a write token and secrets. Checking out the PR head and "
              "running its code hands both to the PR author. Use `pull_request`, or never execute PR code."),
    "WF030": ("error", "script-injection",
              "User-controlled event fields expanded with ${{ }} inside a script become shell code. Pass "
              "them through `env:` and reference the environment variable (\"$TITLE\") instead."),
    "WF040": ("error", "top-level-id-token-write",
              "`id-token: write` lets every job mint OIDC tokens for cloud roles or signing. Grant it only "
              "on the job that needs it."),
    "WF050": ("error", "checkout-persists-credentials",
              "`actions/checkout` writes the GITHUB_TOKEN into .git/config by default, where later steps "
              "and uploaded artifacts can read it. Set `persist-credentials: false` unless the job pushes."),
}

FIRST_PARTY_OWNERS = ("actions", "github")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT_RE = re.compile(r"#\s*v?\d+(\.\d+)*")

# Event fields an outside contributor can set. github.event.* fields not in
# this list (numbers, SHAs, repo ids) are not attacker-controlled text.
_UNTRUSTED = [
    r"github\.event\.issue\.(title|body)",
    r"github\.event\.pull_request\.(title|body)",
    r"github\.event\.pull_request\.head\.(ref|label)",
    r"github\.event\.pull_request\.head\.repo\.default_branch",
    r"github\.event\.comment\.body",
    r"github\.event\.review\.body",
    r"github\.event\.review_comment\.body",
    r"github\.event\.discussion\.(title|body)",
    r"github\.event\.pages\.[^ }]*\.page_name",
    r"github\.event\.commits\.[^ }]*\.(message|author\.(email|name))",
    r"github\.event\.head_commit\.(message|author\.(email|name)|committer\.(email|name))",
    r"github\.event\.workflow_run\.(head_branch|display_title|head_commit\.(message|author\.(email|name)))",
    r"github\.event\.(inputs|client_payload)\.[A-Za-z0-9_.-]+",
    r"github\.head_ref",
]
UNTRUSTED_EXPR_RE = re.compile(r"\$\{\{[^}]*?\b(" + "|".join(_UNTRUSTED) + r")\b[^}]*\}\}")
PR_HEAD_REF_RE = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref)|github\.head_ref|refs/pull/|github\.event\.number"
)
PUSH_RE = re.compile(r"\bgit\s+push\b|\bgh\s+(pr\s+(create|merge)|release\s+create)\b")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str

    @property
    def severity(self) -> str:
        return RULES[self.rule][0]


# -- helpers -------------------------------------------------------------------

def _get(mapping, key, default=None):
    return mapping.get(key, default) if isinstance(mapping, dict) else default


def _line(mapping, key, fallback: int = 1) -> int:
    if isinstance(mapping, YMap):
        return mapping.lines.get(key, fallback)
    return fallback


def _triggers(doc: YMap) -> set[str]:
    # `on` may be a string, a list, or a mapping of events.
    on = doc.get("on", doc.get(True))  # a YAML 1.1 parser would turn `on` into True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def _steps(job) -> list[tuple[YMap, int]]:
    steps = _get(job, "steps")
    if not isinstance(steps, YList):
        return []
    return [(s, steps.lines[i]) for i, s in enumerate(steps) if isinstance(s, YMap)]


def _jobs(doc: YMap) -> list[tuple[str, YMap, int]]:
    jobs = _get(doc, "jobs")
    if not isinstance(jobs, YMap):
        return []
    return [(name, job, jobs.lines.get(name, 1)) for name, job in jobs.items() if isinstance(job, YMap)]


def _action_name(uses: str) -> str:
    return uses.split("@", 1)[0].lower()


# -- rules ---------------------------------------------------------------------

def check_permissions(doc: YMap, path: str) -> list[Finding]:
    out: list[Finding] = []
    if "permissions" not in doc:
        out.append(Finding("WF001", path, 1, "no top-level `permissions:`; the token gets the repository default scopes"))
    else:
        perms = doc["permissions"]
        line = _line(doc, "permissions")
        if isinstance(perms, str) and perms.strip() == "write-all":
            out.append(Finding("WF002", path, line, "top-level `permissions: write-all`"))
        if isinstance(perms, YMap) and str(perms.get("id-token", "")).strip() == "write":
            out.append(Finding("WF040", path, perms.lines.get("id-token", line),
                               "`id-token: write` at the top level; move it to the job that signs or assumes a role"))
    for name, job, _ in _jobs(doc):
        perms = job.get("permissions")
        if isinstance(perms, str) and perms.strip() == "write-all":
            out.append(Finding("WF002", path, _line(job, "permissions"), f"job `{name}` uses `permissions: write-all`"))
    return out


def _uses_entries(doc: YMap):
    """Yield (uses_value, line) for every step `uses:` and job-level reusable-workflow `uses:`."""
    for _, job, job_line in _jobs(doc):
        if isinstance(job.get("uses"), str):
            yield job["uses"], _line(job, "uses", job_line)
        for step, step_line in _steps(job):
            if isinstance(step.get("uses"), str):
                yield step["uses"], _line(step, "uses", step_line)


def check_pinning(doc: YMap, path: str, raw_lines: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for uses, line in _uses_entries(doc):
        uses = uses.strip()
        if uses.startswith("./"):
            continue  # local action or reusable workflow: same commit as the caller
        if uses.startswith("docker://"):
            if "@sha256:" not in uses:
                out.append(Finding("WF012", path, line, f"`{uses}` is not pinned by digest"))
            continue
        if "@" not in uses:
            out.append(Finding("WF010", path, line, f"`{uses}` has no ref at all"))
            continue
        name, ref = uses.rsplit("@", 1)
        owner = name.split("/", 1)[0].lower()
        if SHA_RE.match(ref):
            raw = raw_lines[line - 1] if 0 < line <= len(raw_lines) else ""
            if not VERSION_COMMENT_RE.search(raw.split(ref, 1)[-1]):
                out.append(Finding("WF013", path, line, f"`{name}` is SHA-pinned but has no `# vX.Y.Z` comment"))
            continue
        if owner in FIRST_PARTY_OWNERS:
            out.append(Finding("WF011", path, line, f"first-party `{name}` pinned to `{ref}`, not a commit SHA"))
        else:
            out.append(Finding("WF010", path, line, f"third-party `{name}` pinned to `{ref}`, not a commit SHA"))
    return out


def check_pull_request_target(doc: YMap, path: str) -> list[Finding]:
    if "pull_request_target" not in _triggers(doc):
        return []
    out: list[Finding] = []
    for name, job, _ in _jobs(doc):
        for step, step_line in _steps(job):
            if _action_name(str(step.get("uses", ""))) != "actions/checkout":
                continue
            ref = str(_get(step.get("with"), "ref", ""))
            repo = str(_get(step.get("with"), "repository", ""))
            if PR_HEAD_REF_RE.search(ref) or "pull_request.head.repo" in repo:
                out.append(Finding("WF020", path, _line(step.get("with"), "ref", step_line),
                                   f"job `{name}` checks out the PR head (`ref: {ref}`) under pull_request_target"))
    return out


BLOCK_SCALAR_LINE_RE = re.compile(r":\s*[|>][+-]?[0-9]?\s*(#.*)?$")


def check_script_injection(doc: YMap, path: str, raw_lines: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for name, job, _ in _jobs(doc):
        for step, step_line in _steps(job):
            scripts: list[tuple[str, int]] = []
            if isinstance(step.get("run"), str):
                scripts.append((step["run"], _line(step, "run", step_line)))
            if _action_name(str(step.get("uses", ""))) == "actions/github-script":
                script = _get(step.get("with"), "script")
                if isinstance(script, str):
                    scripts.append((script, _line(step.get("with"), "script", step_line)))
            for text, start in scripts:
                raw = raw_lines[start - 1] if 0 < start <= len(raw_lines) else ""
                first = start + 1 if BLOCK_SCALAR_LINE_RE.search(raw) else start  # `run: |` body starts below
                for offset, line_text in enumerate(text.splitlines() or [text]):
                    for m in UNTRUSTED_EXPR_RE.finditer(line_text):
                        line = first + offset
                        out.append(Finding("WF030", path, line,
                                           f"job `{name}` expands `{m.group(1)}` directly in a script"))
    return out


def _job_pushes(job: YMap) -> bool:
    perms = job.get("permissions")
    if isinstance(perms, YMap) and str(perms.get("contents", "")).strip() == "write":
        return True
    if isinstance(perms, str) and perms.strip() == "write-all":
        return True
    return any(isinstance(s.get("run"), str) and PUSH_RE.search(s["run"]) for s, _ in _steps(job))


def check_persist_credentials(doc: YMap, path: str) -> list[Finding]:
    out: list[Finding] = []
    for name, job, _ in _jobs(doc):
        if _job_pushes(job):
            continue
        for step, step_line in _steps(job):
            if _action_name(str(step.get("uses", ""))) != "actions/checkout":
                continue
            value = str(_get(step.get("with"), "persist-credentials", "true")).strip().lower()
            if value != "false":
                out.append(Finding("WF050", path, step_line,
                                   f"job `{name}` checks out without `persist-credentials: false`"))
    return out


# -- driver --------------------------------------------------------------------

def lint_text(text: str, path: str) -> list[Finding]:
    try:
        doc = parse(text)
    except YamlSubsetError as exc:
        return [Finding("WF000", path, 1, str(exc))]
    if not isinstance(doc, YMap):
        return [Finding("WF000", path, 1, "top level is not a mapping")]
    raw_lines = text.splitlines()
    findings = (
        check_permissions(doc, path)
        + check_pinning(doc, path, raw_lines)
        + check_pull_request_target(doc, path)
        + check_script_injection(doc, path, raw_lines)
        + check_persist_credentials(doc, path)
    )
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(x for x in path.iterdir() if x.suffix in (".yml", ".yaml") and x.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(p)
    return files


def _display(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def render_text(findings: list[Finding], files: list[Path], base: Path | None) -> str:
    lines = [f"{f.path}:{f.line}: {f.severity.upper()} {f.rule} {RULES[f.rule][1]}: {f.message}" for f in findings]
    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    by_file: dict[str, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.path, []).append(f)
    if lines:
        lines.append("")
    lines.append("per file (errors/warnings):")
    for p in files:
        d = _display(p, base)
        fs = by_file.get(d, [])
        e = sum(f.severity == "error" for f in fs)
        w = sum(f.severity == "warning" for f in fs)
        lines.append(f"  {'FAIL' if e else 'ok  '} {d}  {e}/{w}")
    lines.append(f"{len(files)} file(s) checked: {errors} error(s), {warnings} warning(s)")
    return "\n".join(lines)


def render_sarif(findings: list[Finding]) -> dict:
    level = {"error": "error", "warning": "warning", "note": "note"}
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": TOOL_NAME,
                "version": TOOL_VERSION,
                "informationUri": "https://docs.github.com/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions",
                "rules": [{
                    "id": rid,
                    "name": name,
                    "shortDescription": {"text": name.replace("-", " ")},
                    "fullDescription": {"text": help_text},
                    "help": {"text": help_text},
                    "defaultConfiguration": {"level": level[sev]},
                } for rid, (sev, name, help_text) in RULES.items()],
            }},
            "results": [{
                "ruleId": f.rule,
                "level": level[f.severity],
                "message": {"text": f.message},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": f.path},
                    "region": {"startLine": max(1, f.line)},
                }}],
            } for f in findings],
        }],
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="check_workflows.py", description="GitHub Actions workflow hardening linter")
    p.add_argument("paths", nargs="*", default=[".github/workflows"], help="workflow files or directories")
    p.add_argument("--format", choices=("text", "sarif"), default="text")
    p.add_argument("--output", help="write the report here instead of stdout")
    p.add_argument("--fail-on", choices=("error", "warning"), default="error",
                   help="lowest severity that makes the exit status 1 (default: error)")
    p.add_argument("--uri-base", help="report paths relative to this directory (e.g. the repo root, for SARIF)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = Path(args.uri_base) if args.uri_base else None
    try:
        files = collect_files(args.paths)
    except FileNotFoundError as exc:
        print(f"check_workflows: no such file or directory: {exc}", file=sys.stderr)
        return 2
    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_text(f.read_text(encoding="utf-8"), _display(f, base)))
    if args.format == "sarif":
        out = json.dumps(render_sarif(findings), indent=2)
    else:
        out = render_text(findings, files, base)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    threshold = SEVERITY_ORDER[args.fail_on]
    return 1 if any(SEVERITY_ORDER[f.severity] >= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
