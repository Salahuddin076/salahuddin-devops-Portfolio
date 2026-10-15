#!/usr/bin/env python3
"""Promote an immutable image tag between environments in the config repo (stdlib only).

  promote.py --from dev --to staging            copy envs/dev image.tag into envs/staging
  promote.py --tag <sha> --to dev               set a new tag in the first env (what app CI does)
  promote.py --from dev --to prod --force-hotfix --reason "..."   skip staging, recorded in trailers

The edit is a minimal YAML-subset rewrite: only the `tag:` line inside the
top-level `image:` block changes, so comments, ordering and formatting are
kept byte for byte. Options:

  --config-repo DIR   the config repository (default: ../config-repo next to scripts/)
  --dry-run           print the summary and PR body, write nothing
  --commit            git-commit the change in --config-repo (optionally on --branch NAME)
  --pr-body FILE      also write the PR body (Markdown) to FILE

Exit status: 0 promoted (or nothing to do), 1 refused by policy, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CHAIN = ("dev", "staging", "prod")
DEFAULT_REPO = Path(__file__).resolve().parent.parent / "config-repo"

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SEMVER_SHA = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-[0-9a-f]{7,40}$")
IMAGE_LINE = re.compile(r"^image:[ \t]*(#.*)?$")
TAG_LINE = re.compile(r"^(?P<indent>[ \t]+)tag:(?P<sp>[ \t]*)(?P<value>\"[^\"]*\"|'[^']*'|[^\s#]+)"
                      r"(?P<rest>[ \t]*(#.*)?)$")


class PromotionError(Exception):
    """Refused by policy (exit 1)."""


class UsageError(Exception):
    """Bad input or unreadable files (exit 2)."""


def validate_tag(tag: str) -> str:
    """Return the tag if it is immutable, else raise PromotionError with the reason."""
    if tag.lower() == "latest":
        raise PromotionError("tag 'latest' is mutable and never deployable")
    if SHA40.match(tag) or SEMVER_SHA.match(tag):
        return tag
    raise PromotionError(f"tag {tag!r} is not immutable: use a 40-char git SHA or <semver>-<7..40 hex sha>")


def next_env(env: str) -> str | None:
    i = CHAIN.index(env)
    return CHAIN[i + 1] if i + 1 < len(CHAIN) else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _find_tag_line(lines: list[str], path: str) -> tuple[int, re.Match]:
    """Locate the single `tag:` line directly under the top-level `image:` key."""
    starts = [i for i, ln in enumerate(lines) if IMAGE_LINE.match(ln.rstrip("\r\n"))]
    if len(starts) != 1:
        raise UsageError(f"{path}: expected exactly one top-level 'image:' block, found {len(starts)}")
    child_indent = None
    found: list[tuple[int, re.Match]] = []
    for i in range(starts[0] + 1, len(lines)):
        text = lines[i].rstrip("\r\n")
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        indent = len(text) - len(text.lstrip(" \t"))
        if indent == 0:
            break  # next top-level key: end of the image block
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue  # deeper nesting is not image.tag
        m = TAG_LINE.match(text)
        if m:
            found.append((i, m))
    if len(found) != 1:
        raise UsageError(f"{path}: expected exactly one 'tag:' line under 'image:', found {len(found)}")
    return found[0]


def read_tag(text: str, path: str = "values.yaml") -> str:
    lines = text.splitlines(keepends=True)
    _, m = _find_tag_line(lines, path)
    return _unquote(m.group("value"))


def replace_tag(text: str, new_tag: str, path: str = "values.yaml") -> str:
    """Rewrite only the image.tag line; keep quoting style, trailing comment and line ending."""
    lines = text.splitlines(keepends=True)
    i, m = _find_tag_line(lines, path)
    old = m.group("value")
    quote = old[0] if old[:1] in "\"'" and old[-1:] == old[:1] else ""
    ending = lines[i][len(lines[i].rstrip("\r\n")):]
    lines[i] = f"{m.group('indent')}tag:{m.group('sp')}{quote}{new_tag}{quote}{m.group('rest')}{ending}"
    return "".join(lines)


@dataclass
class Plan:
    source: str | None
    target: str
    old_tag: str
    new_tag: str
    hotfix: bool
    reason: str
    rel_path: str
    old_text: str
    new_text: str

    @property
    def noop(self) -> bool:
        return self.old_tag == self.new_tag

    def diff(self) -> str:
        return "".join(difflib.unified_diff(self.old_text.splitlines(keepends=True),
                                            self.new_text.splitlines(keepends=True),
                                            fromfile=f"a/{self.rel_path}", tofile=f"b/{self.rel_path}", n=1))

    def commit_message(self) -> str:
        origin = self.source or "ci"
        subject = f"{self.target}: promote orders-api {self.new_tag} from {origin}"
        if self.hotfix:
            subject = f"{self.target}: HOTFIX orders-api {self.new_tag} from {origin}"
        body = [subject, "", f"image.tag {self.old_tag} -> {self.new_tag} in {self.rel_path}.", ""]
        trailers = [f"Promoted-From: {origin}", f"Promoted-To: {self.target}", f"Image-Tag: {self.new_tag}"]
        if self.hotfix:
            trailers += ["Promotion-Hotfix: true", f"Hotfix-Reason: {self.reason}"]
        return "\n".join(body + trailers) + "\n"

    def pr_body(self) -> str:
        origin = self.source or "ci"
        out = [f"## Promote orders-api to `{self.target}`", "",
               "| | |", "|---|---|",
               f"| From | `{origin}` |", f"| To | `{self.target}` |",
               f"| Old tag | `{self.old_tag}` |", f"| New tag | `{self.new_tag}` |",
               f"| File | `{self.rel_path}` |", ""]
        if self.hotfix:
            out += [f"> **Hotfix**: skips the normal chain ({' -> '.join(CHAIN)}). Reason: {self.reason}",
                    "> Recorded as `Promotion-Hotfix: true` in the commit trailers.", ""]
        out += ["```diff", self.diff().rstrip("\n"), "```", "",
                "Checklist:",
                f"- [ ] `{self.new_tag}` is healthy in `{origin}`" if self.source else
                "- [ ] CI built and pushed this tag from the app repo",
                "- [ ] Argo CD diff for the target app shows only the image change"]
        if self.target == "prod":
            out.append("- [ ] Merge inside the prod sync window; the canary analysis gates the rollout")
        return "\n".join(out) + "\n"


def plan_promotion(repo: Path, target: str, source: str | None = None, tag: str | None = None,
                   force_hotfix: bool = False, reason: str = "") -> Plan:
    if target not in CHAIN:
        raise UsageError(f"unknown environment {target!r} (chain: {' -> '.join(CHAIN)})")
    if (source is None) == (tag is None):
        raise UsageError("give exactly one of --from ENV or --tag TAG")
    if force_hotfix and not reason.strip():
        raise UsageError("--force-hotfix needs --reason")
    if source is not None:
        if source not in CHAIN:
            raise UsageError(f"unknown environment {source!r} (chain: {' -> '.join(CHAIN)})")
        if source == target:
            raise UsageError("--from and --to are the same environment")
        expected = next_env(source)
        if target != expected and not force_hotfix:
            hint = f"the next env after {source} is {expected}" if expected else f"{source} is the last env"
            raise PromotionError(f"refusing {source} -> {target}: {hint} "
                                 f"(chain {' -> '.join(CHAIN)}); use --force-hotfix --reason to override")
        new_tag = read_tag(_read(repo / "envs" / source / "values.yaml"), f"envs/{source}/values.yaml")
    else:
        if target != CHAIN[0] and not force_hotfix:
            raise PromotionError(f"refusing --tag into {target}: new tags enter at {CHAIN[0]}; "
                                 "promote them along the chain (or --force-hotfix --reason)")
        new_tag = tag
    validate_tag(new_tag)
    rel = f"envs/{target}/values.yaml"
    old_text = _read(repo / rel)
    old_tag = read_tag(old_text, rel)
    new_text = old_text if old_tag == new_tag else replace_tag(old_text, new_tag, rel)
    return Plan(source, target, old_tag, new_tag, force_hotfix, reason.strip(), rel, old_text, new_text)


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror}") from exc


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise UsageError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def apply(plan: Plan, repo: Path, commit: bool = False, branch: str | None = None) -> str | None:
    """Write the file; optionally commit. Returns the new commit SHA when committing."""
    if commit and git(repo, "status", "--porcelain", "--", plan.rel_path):
        raise UsageError(f"{plan.rel_path} has uncommitted changes; refusing to mix them into the promotion")
    if branch and commit:
        git(repo, "switch", "-c", branch)
    (repo / plan.rel_path).write_bytes(plan.new_text.encode("utf-8"))
    if not commit:
        return None
    git(repo, "add", "--", plan.rel_path)
    proc = subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-F", "-"], input=plan.commit_message(),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise UsageError(f"git commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return git(repo, "rev-parse", "HEAD")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="promote.py", description="Promote an image tag along dev -> staging -> prod.")
    p.add_argument("--from", dest="source", choices=CHAIN, help="environment to copy image.tag from")
    p.add_argument("--tag", help="set this tag directly (only into the first env unless --force-hotfix)")
    p.add_argument("--to", dest="target", required=True, choices=CHAIN, help="environment to update")
    p.add_argument("--config-repo", type=Path, default=DEFAULT_REPO, help="config repository root")
    p.add_argument("--force-hotfix", action="store_true", help="allow skipping an env; recorded in trailers")
    p.add_argument("--reason", default="", help="why the hotfix skips the chain (required with --force-hotfix)")
    p.add_argument("--dry-run", action="store_true", help="show the change, write nothing")
    p.add_argument("--commit", action="store_true", help="git-commit the change in --config-repo")
    p.add_argument("--branch", help="with --commit: create this branch first")
    p.add_argument("--pr-body", type=Path, help="write the PR body (Markdown) to this file")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    repo = args.config_repo
    try:
        plan = plan_promotion(repo, args.target, args.source, args.tag, args.force_hotfix, args.reason)
        origin = plan.source or "ci"
        if plan.noop:
            print(f"promote: {args.target} already runs {plan.new_tag}; nothing to do")
            return 0
        print(f"promote: {origin} -> {plan.target}  {plan.old_tag} -> {plan.new_tag}"
              + ("  [HOTFIX]" if plan.hotfix else ""))
        sha = None
        if args.dry_run:
            print(f"dry run: {plan.rel_path} not written")
        else:
            sha = apply(plan, repo, commit=args.commit, branch=args.branch)
            print(f"wrote {plan.rel_path}" + (f", committed {sha[:12]}" if sha else ""))
        if args.pr_body:
            args.pr_body.write_text(plan.pr_body(), encoding="utf-8")
        print("--- commit message ---")
        print(plan.commit_message(), end="")
        print("--- PR body ---")
        print(plan.pr_body(), end="")
        return 0
    except PromotionError as exc:
        print(f"promote: REFUSED: {exc}", file=sys.stdout)
        return 1
    except UsageError as exc:
        print(f"promote: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
