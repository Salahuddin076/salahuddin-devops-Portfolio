#!/usr/bin/env python3
"""GitOps guardrails for the config repo: Argo CD manifests plus environment values (stdlib only).

  check_gitops_policy.py [--config-repo DIR] [--fail-on error|warning] [--format text|json]

It reads every manifest under <config-repo>/argocd/, expands each
ApplicationSet's git directory generator over the repo (the same envs/*
directories Argo CD would find), applies the template and templatePatch, and
then checks the resulting Applications against their AppProjects and the
values files they deploy.

The templatePatch renderer understands only what this repo uses:
`{{ .path.basename }}` / `{{ .path.path }}` and if / else if / else / end on
`eq .path.basename "<literal>"`. Anything else is a GP000 error, so the check
fails closed instead of guessing.

Rules:
  GP000 error    a manifest or template the checker cannot read
  GP001 error    the prod Application has automated sync
  GP002 error    prune enabled outside dev
  GP003 error    an AppProject used by an ApplicationSet allows cluster-scoped kinds
  GP004 error    an Application's destination or repo is not allowed by its AppProject
  GP005 error    an environment's image.tag is latest or not immutable
  GP006 error    prod does not render a Rollout gated by an AnalysisTemplate
  GP007 error    prod can be synced outside business hours (deny windows incomplete or manualSync allowed)
  GP008 warning  an environment Application lacks sync-failed / health-degraded notifications
  GP009 error    HPA-managed replicas are not in ignoreDifferences (Deployment and Rollout)
  GP010 error    dev is not automated with selfHeal and prune, or staging is not automated

Exit status: 0 clean at --fail-on, 1 findings, 2 usage error.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml_lite  # noqa: E402
from promote import PromotionError, UsageError, read_tag, validate_tag  # noqa: E402

DEFAULT_REPO = Path(__file__).resolve().parent.parent / "config-repo"
RULES = {
    "GP000": "error", "GP001": "error", "GP002": "error", "GP003": "error", "GP004": "error",
    "GP005": "error", "GP006": "error", "GP007": "error", "GP008": "warning", "GP009": "error",
    "GP010": "error",
}
NOTIFY = ("notifications.argoproj.io/subscribe.on-sync-failed.", "notifications.argoproj.io/subscribe.on-health-degraded.")


@dataclass(frozen=True)
class Finding:
    rule: str
    subject: str
    message: str

    @property
    def severity(self) -> str:
        return RULES[self.rule]


@dataclass
class App:
    name: str
    doc: dict
    source_file: str
    env: str | None = None          # set for Applications generated from env directories
    appset: str | None = None

    @property
    def spec(self) -> dict:
        return self.doc.get("spec") or {}

    @property
    def sync(self) -> dict:
        return self.spec.get("syncPolicy") or {}

    @property
    def automated(self) -> dict | None:
        a = self.sync.get("automated")
        return a if isinstance(a, dict) else ({} if a is True else None)


@dataclass
class Context:
    repo: Path
    projects: dict[str, dict] = field(default_factory=dict)
    apps: list[App] = field(default_factory=list)
    appsets: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, subject: str, message: str) -> None:
        self.findings.append(Finding(rule, subject, message))


# -- a deliberately tiny Go-template subset -------------------------------------

_ACTION = re.compile(r"(\{\{-?.*?-?\}\})", re.S)
_COND = re.compile(r'^eq\s+\.path\.basename\s+"([^"]*)"$')
_FIELD = re.compile(r"^\.path\.(basename|path)$")


class TemplateError(ValueError):
    pass


def render_go(template: str, params: dict) -> str:
    parts = _ACTION.split(template)
    # trim markers: `{{-` eats whitespace before, `-}}` eats whitespace after
    for i in range(1, len(parts), 2):
        if parts[i].startswith("{{-"):
            parts[i - 1] = parts[i - 1].rstrip()
        if parts[i].endswith("-}}"):
            parts[i + 1] = parts[i + 1].lstrip()
    out: list[str] = []
    # stack of [taking_branch_now, some_branch_already_taken]
    stack: list[list[bool]] = []

    def active() -> bool:
        return all(s[0] for s in stack)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            if active():
                out.append(part)
            continue
        action = part.strip("{}").strip("-").strip()
        if action.startswith("if "):
            ok = _cond(action[3:].strip(), params)
            stack.append([ok, ok])
        elif action.startswith("else if "):
            if not stack:
                raise TemplateError("else without if")
            ok = not stack[-1][1] and _cond(action[8:].strip(), params)
            stack[-1] = [ok, stack[-1][1] or ok]
        elif action == "else":
            if not stack:
                raise TemplateError("else without if")
            stack[-1] = [not stack[-1][1], True]
        elif action == "end":
            if not stack:
                raise TemplateError("end without if")
            stack.pop()
        else:
            m = _FIELD.match(action)
            if not m:
                raise TemplateError(f"unsupported template action {{{{ {action} }}}}")
            if active():
                out.append(params[m.group(1)])
    if stack:
        raise TemplateError("unterminated if")
    return "".join(out)


def _cond(expr: str, params: dict) -> bool:
    m = _COND.match(expr)
    if not m:
        raise TemplateError(f"unsupported condition {expr!r}")
    return params["basename"] == m.group(1)


def _render_strings(obj, params):
    if isinstance(obj, dict):
        return {k: _render_strings(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_strings(v, params) for v in obj]
    if isinstance(obj, str) and "{{" in obj:
        return render_go(obj, params)
    return obj


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# -- loading -------------------------------------------------------------------

def load(ctx: Context) -> None:
    argocd = ctx.repo / "argocd"
    files = sorted(argocd.rglob("*.yaml")) if argocd.is_dir() else []
    if not files:
        ctx.add("GP000", str(argocd), "no manifests found")
    for f in files:
        rel = f.relative_to(ctx.repo).as_posix()
        try:
            docs = yaml_lite.load_all(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            ctx.add("GP000", rel, f"cannot parse: {exc}")
            continue
        for d in docs:
            kind, name = d.get("kind"), (d.get("metadata") or {}).get("name", "?")
            if kind == "AppProject":
                ctx.projects[name] = d
            elif kind == "Application":
                ctx.apps.append(App(name, d, rel))
            elif kind == "ApplicationSet":
                ctx.appsets.append(d)
                expand(ctx, d, rel)


def expand(ctx: Context, appset: dict, rel: str) -> None:
    spec = appset.get("spec") or {}
    name = appset["metadata"]["name"]
    if not spec.get("goTemplate"):
        ctx.add("GP000", f"ApplicationSet/{name}", "only goTemplate: true ApplicationSets are supported")
        return
    for gen in spec.get("generators") or []:
        git = gen.get("git") if isinstance(gen, dict) else None
        if not git or "directories" not in git:
            ctx.add("GP000", f"ApplicationSet/{name}", f"unsupported generator {sorted(gen)}")
            continue
        include = [d["path"] for d in git["directories"] if not d.get("exclude")]
        exclude = [d["path"] for d in git["directories"] if d.get("exclude")]
        dirs = sorted({p for pat in include for p in ctx.repo.glob(pat) if p.is_dir()})
        for d in dirs:
            path = d.relative_to(ctx.repo).as_posix()
            if any(fnmatch.fnmatch(path, x) for x in exclude):
                continue
            params = {"basename": d.name, "path": path}
            try:
                app = _render_strings(spec.get("template") or {}, params)
                if spec.get("templatePatch"):
                    patch = yaml_lite.load_all(render_go(spec["templatePatch"], params))
                    if patch:
                        app = deep_merge(app, patch[0])
            except (TemplateError, ValueError) as exc:
                ctx.add("GP000", f"ApplicationSet/{name}", f"cannot render for {path}: {exc}")
                continue
            app = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", **app}
            ctx.apps.append(App(app["metadata"]["name"], app, rel, env=d.name, appset=name))


# -- rules ---------------------------------------------------------------------

def _match(pattern: str | None, value: str | None) -> bool:
    if pattern is None:
        return value is None
    return fnmatch.fnmatchcase(value or "", pattern)


def check_sync(ctx: Context) -> None:
    for app in ctx.apps:
        subject = f"Application/{app.name}"
        auto = app.automated
        if app.env == "prod" and auto is not None:
            ctx.add("GP001", subject, "prod must be synced by hand; remove syncPolicy.automated")
        if auto is not None and auto.get("prune") is True and app.env != "dev":
            ctx.add("GP002", subject, f"prune is enabled in {app.env or 'a non-env app'}; only dev may prune")
        if app.env == "dev" and not (auto is not None and auto.get("selfHeal") is True and auto.get("prune") is True):
            ctx.add("GP010", subject, "dev must be automated with selfHeal and prune")
        if app.env == "staging" and auto is None:
            ctx.add("GP010", subject, "staging must be automated (without prune)")


def check_projects(ctx: Context) -> None:
    used = {((a.get("spec") or {}).get("template") or {}).get("spec", {}).get("project") for a in ctx.appsets}
    for name in sorted(n for n in used if n):
        proj = ctx.projects.get(name)
        if proj is None:
            ctx.add("GP003", f"AppProject/{name}", "used by an ApplicationSet but not defined")
            continue
        whitelist = (proj.get("spec") or {}).get("clusterResourceWhitelist") or []
        if whitelist:
            kinds = ", ".join(f"{w.get('group') or 'core'}/{w.get('kind')}" for w in whitelist)
            ctx.add("GP003", f"AppProject/{name}", f"allows cluster-scoped kinds ({kinds}); must be []")


def check_destinations(ctx: Context) -> None:
    for app in ctx.apps:
        subject = f"Application/{app.name}"
        pname = app.spec.get("project", "default")
        proj = ctx.projects.get(pname)
        if proj is None:
            ctx.add("GP004", subject, f"project {pname!r} is not defined")
            continue
        pspec = proj.get("spec") or {}
        dest = app.spec.get("destination") or {}
        ns, server, cname = dest.get("namespace"), dest.get("server"), dest.get("name")
        allowed = False
        for d in pspec.get("destinations") or []:
            if not _match(d.get("namespace", "*"), ns):
                continue
            if server is not None and _match(d.get("server", "*"), server):
                allowed = True
            if cname is not None and "name" in d and _match(d["name"], cname):
                allowed = True
        if not allowed:
            ctx.add("GP004", subject, f"destination {server or cname} namespace {ns!r} not allowed by project {pname}")
        repos = pspec.get("sourceRepos") or []
        sources = [app.spec["source"]] if "source" in app.spec else app.spec.get("sources") or []
        for s in sources:
            if not any(_match(r, s.get("repoURL")) for r in repos):
                ctx.add("GP004", subject, f"repo {s.get('repoURL')} not in project {pname} sourceRepos")


def _values_for(ctx: Context, app: App) -> tuple[Path | None, list[Path]]:
    src = app.spec.get("source") or {}
    if not src.get("path"):
        return None, []
    chart = (ctx.repo / src["path"]).resolve()
    files = [(chart / v).resolve() for v in (src.get("helm") or {}).get("valueFiles") or []]
    return chart, files


def check_env_values(ctx: Context) -> None:
    for app in (a for a in ctx.apps if a.env):
        subject = f"Application/{app.name}"
        chart, files = _values_for(ctx, app)
        values: dict = {}
        for f in files:
            rel = _rel(ctx, f)
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                ctx.add("GP000", subject, f"value file {rel} not found")
                continue
            try:
                validate_tag(read_tag(text, rel))
            except PromotionError as exc:
                ctx.add("GP005", rel, str(exc))
            except UsageError as exc:
                ctx.add("GP005", rel, str(exc))
            try:
                values = deep_merge(values, (yaml_lite.load_all(text) or [{}])[0])
            except ValueError as exc:
                ctx.add("GP000", rel, f"cannot parse: {exc}")
        if app.env != "prod":
            continue
        rollout = values.get("rollout") or {}
        if rollout.get("enabled") is not True:
            ctx.add("GP006", subject, "prod values must set rollout.enabled: true (canary with analysis)")
        if not (rollout.get("analysis") or {}).get("templateName"):
            ctx.add("GP006", subject, "prod values must name rollout.analysis.templateName")
        templates = list((chart / "templates").glob("*.yaml")) if chart and chart.is_dir() else []
        text = "\n".join(t.read_text(encoding="utf-8") for t in templates)
        if "kind: AnalysisTemplate" not in text or "templateName:" not in text:
            ctx.add("GP006", subject, f"chart {_rel(ctx, chart) if chart else '?'} has no AnalysisTemplate "
                                      "referenced from the Rollout steps")


def check_ignore_and_notify(ctx: Context) -> None:
    for app in (a for a in ctx.apps if a.env):
        subject = f"Application/{app.name}"
        rules = app.spec.get("ignoreDifferences") or []
        for group, kind in (("apps", "Deployment"), ("argoproj.io", "Rollout")):
            if not any(r.get("group", "") == group and r.get("kind") == kind and "/spec/replicas" in
                       (r.get("jsonPointers") or []) for r in rules):
                ctx.add("GP009", subject, f"ignoreDifferences lacks {group}/{kind} /spec/replicas (the HPA owns it)")
        if "RespectIgnoreDifferences=true" not in (app.sync.get("syncOptions") or []):
            ctx.add("GP009", subject, "syncOptions lacks RespectIgnoreDifferences=true, so a sync resets replicas")
        ann = (app.doc.get("metadata") or {}).get("annotations") or {}
        for prefix in NOTIFY:
            if not any(k.startswith(prefix) for k in ann):
                ctx.add("GP008", subject, f"no {prefix}<service> annotation")


# -- sync windows ----------------------------------------------------------------

def _cron_field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if not (lo <= a <= b <= hi):
            raise ValueError(f"cron value out of range: {spec}")
        out.update(range(a, b + 1, step))
    return out


def _duration(text: str) -> timedelta:
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", text.strip())
    if not m or not any(m.groups()):
        raise ValueError(f"bad duration {text!r}")
    return timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))


def window_minutes(schedule: str, duration: str, week_start: datetime) -> set[int]:
    """Minutes (offset from week_start) of one week covered by the window; starts may fall in the week before."""
    fields = schedule.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs 5 fields: {schedule!r}")
    minute, hour = _cron_field(fields[0], 0, 59), _cron_field(fields[1], 0, 23)
    dom, month = _cron_field(fields[2], 1, 31), _cron_field(fields[3], 1, 12)
    dow = {d % 7 for d in _cron_field(fields[4], 0, 7)}
    length = int(_duration(duration).total_seconds() // 60)
    covered: set[int] = set()
    t = week_start - timedelta(days=7)
    end = week_start + timedelta(days=7)
    while t < end:
        cron_dow = (t.weekday() + 1) % 7  # cron: 0 = Sunday
        if t.minute in minute and t.hour in hour and t.day in dom and t.month in month and cron_dow in dow:
            start = int((t - week_start).total_seconds() // 60)
            covered.update(m for m in range(start, start + length) if 0 <= m < 7 * 24 * 60)
        t += timedelta(minutes=1)
    return covered


def check_windows(ctx: Context, business: tuple[int, int]) -> None:
    week_start = datetime(2026, 1, 5)  # a Monday, 00:00
    open_minutes = {d * 1440 + m for d in range(5) for m in range(business[0] * 60, business[1] * 60)}
    must_deny = set(range(7 * 1440)) - open_minutes
    for app in (a for a in ctx.apps if a.env == "prod"):
        subject = f"Application/{app.name}"
        proj = ctx.projects.get(app.spec.get("project", "default")) or {}
        covered: set[int] = set()
        for w in (proj.get("spec") or {}).get("syncWindows") or []:
            if w.get("kind") != "deny":
                continue
            if not any(fnmatch.fnmatchcase(app.name, p) for p in w.get("applications") or []):
                continue
            if w.get("manualSync") is True:
                ctx.add("GP007", subject, f"deny window {w.get('schedule')!r} sets manualSync: true, so it "
                                          "does not stop a manual prod sync")
                continue
            if (w.get("timeZone") or "UTC") != "UTC":
                ctx.add("GP007", subject, f"window {w.get('schedule')!r} uses {w.get('timeZone')}; only UTC is checked")
                continue
            try:
                covered |= window_minutes(str(w.get("schedule", "")), str(w.get("duration", "")), week_start)
            except ValueError as exc:
                ctx.add("GP000", subject, f"sync window: {exc}")
        gaps = sorted(must_deny - covered)
        if gaps:
            first = week_start + timedelta(minutes=gaps[0])
            ctx.add("GP007", subject, f"prod can sync outside {business[0]:02d}:00-{business[1]:02d}:00 Mon-Fri UTC: "
                                      f"{len(gaps) // 60}h{len(gaps) % 60:02d}m a week uncovered, first at "
                                      f"{first:%a %H:%M}")


# -- driver ----------------------------------------------------------------------

def _rel(ctx: Context, p: Path) -> str:
    try:
        return p.resolve().relative_to(ctx.repo.resolve()).as_posix()
    except ValueError:
        return str(p)


def run(repo: Path, business: tuple[int, int] = (8, 17)) -> Context:
    ctx = Context(repo=repo)
    load(ctx)
    check_sync(ctx)
    check_projects(ctx)
    check_destinations(ctx)
    check_env_values(ctx)
    check_ignore_and_notify(ctx)
    check_windows(ctx, business)
    return ctx


def describe(app: App, ctx: Context) -> str:
    auto = app.automated
    if auto is None:
        mode = "manual"
    else:
        mode = "automated" + (" selfHeal" if auto.get("selfHeal") else "") + (" prune" if auto.get("prune") else "")
    dest = app.spec.get("destination") or {}
    origin = f"ApplicationSet/{app.appset}" if app.appset else app.source_file
    if app.env == "prod":
        proj = ctx.projects.get(app.spec.get("project", "")) or {}
        n = sum(1 for w in (proj.get("spec") or {}).get("syncWindows") or []
                if w.get("kind") == "deny" and any(fnmatch.fnmatchcase(app.name, p) for p in w.get("applications") or []))
        mode += f", {n} deny window(s)"
    return f"  {app.name:<20} {app.spec.get('project', ''):<11} ns {dest.get('namespace', ''):<17} {mode}  ({origin})"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_gitops_policy.py", description="Argo CD + env values guardrails")
    p.add_argument("--config-repo", type=Path, default=DEFAULT_REPO)
    p.add_argument("--fail-on", choices=("error", "warning"), default="error")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--business-hours", default="8-17", help="UTC hours prod may sync, Mon-Fri (default 8-17)")
    args = p.parse_args(argv)
    try:
        a, b = (int(x) for x in args.business_hours.split("-", 1))
        if not 0 <= a < b <= 24:
            raise ValueError
    except ValueError:
        print("check_gitops_policy: --business-hours must look like 8-17", file=sys.stderr)
        return 2
    if not args.config_repo.is_dir():
        print(f"check_gitops_policy: no such directory: {args.config_repo}", file=sys.stderr)
        return 2
    ctx = run(args.config_repo, (a, b))
    findings = sorted(ctx.findings, key=lambda f: (f.rule, f.subject, f.message))
    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    if args.format == "json":
        print(json.dumps({
            "applications": [{"name": x.name, "env": x.env, "project": x.spec.get("project"),
                              "namespace": (x.spec.get("destination") or {}).get("namespace"),
                              "automated": x.automated} for x in ctx.apps],
            "findings": [{"rule": f.rule, "severity": f.severity, "subject": f.subject, "message": f.message}
                         for f in findings],
        }, indent=2, sort_keys=True))
    else:
        generated = sum(1 for x in ctx.apps if x.appset)
        print(f"check_gitops_policy: {len(ctx.projects)} AppProject(s), {len(ctx.apps)} Application(s) "
              f"({generated} generated from {len(ctx.appsets)} ApplicationSet(s))")
        for app in ctx.apps:
            print(describe(app, ctx))
        for f in findings:
            print(f"{f.severity.upper():<7} {f.rule} {f.subject}: {f.message}")
        print(f"{errors} error(s), {warnings} warning(s)")
    threshold = {"error": ("error",), "warning": ("error", "warning")}[args.fail_on]
    return 1 if any(f.severity in threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
