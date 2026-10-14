#!/usr/bin/env python3
"""Validate a .trivyignore file: every exception expires and says why.

Usage:
  trivyignore_check.py [FILE ...] [--today YYYY-MM-DD] [--max-days N]

Each non-comment line is one ignored finding. Accepted forms:

  CVE-2023-45853 exp:2027-01-31 # reason: why it is acceptable
  CVE-2023-45853 # exp:2027-01-31 reason: why it is acceptable

The first form is preferred: `exp:` as a field is Trivy's own syntax, so
Trivy itself stops honouring the entry after that date. The second form is
accepted for teams that keep the date in the comment.

Rules (all errors):
  TI001  entry has no exp:YYYY-MM-DD date (or the date is not a real date)
  TI002  entry has no reason after `#`
  TI003  entry expired (exp date earlier than today)
  TI004  expiry further than --max-days in the future (default 180)
  TI005  the finding ID is listed more than once

Exit status: 0 clean, 1 findings, 2 file missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EXP_RE = re.compile(r"(?:^|\s)exp:(\S+)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_MAX_DAYS = 180


@dataclass(frozen=True)
class Problem:
    rule: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class Entry:
    finding_id: str
    expires: dt.date | None
    reason: str
    line: int


def _parse_date(text: str) -> dt.date | None:
    if not DATE_RE.match(text):
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def check_text(text: str, path: str, today: dt.date, max_days: int = DEFAULT_MAX_DAYS) -> tuple[list[Entry], list[Problem]]:
    entries: list[Entry] = []
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        body, _, comment = line.partition("#")
        fields = body.split()
        finding_id = fields[0] if fields else ""
        if not finding_id:
            problems.append(Problem("TI001", path, n, "entry has no finding ID"))
            continue

        exp_text = None
        m = EXP_RE.search(body) or EXP_RE.search(comment)
        if m:
            exp_text = m.group(1)
        reason = EXP_RE.sub(" ", comment).strip()
        reason = re.sub(r"^reason:\s*", "", reason, flags=re.IGNORECASE).strip()

        expires = _parse_date(exp_text) if exp_text else None
        if exp_text is None:
            problems.append(Problem("TI001", path, n, f"{finding_id}: no exp:YYYY-MM-DD expiry"))
        elif expires is None:
            problems.append(Problem("TI001", path, n, f"{finding_id}: exp:{exp_text} is not a valid YYYY-MM-DD date"))
        if not reason:
            problems.append(Problem("TI002", path, n, f"{finding_id}: no reason after '#'"))
        if expires is not None:
            if expires < today:
                problems.append(Problem("TI003", path, n, f"{finding_id}: expired on {expires.isoformat()}"))
            elif (expires - today).days > max_days:
                problems.append(Problem("TI004", path, n,
                                        f"{finding_id}: expiry {expires.isoformat()} is more than {max_days} days away"))
        if finding_id in seen:
            problems.append(Problem("TI005", path, n, f"{finding_id}: already listed on line {seen[finding_id]}"))
        else:
            seen[finding_id] = n
        entries.append(Entry(finding_id, expires, reason, n))
    return entries, problems


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trivyignore_check.py", description="Validate .trivyignore expiries and reasons")
    p.add_argument("files", nargs="*", default=[".trivyignore"])
    p.add_argument("--today", type=dt.date.fromisoformat, default=None, help="override today's date (tests, audits)")
    p.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = args.today or dt.date.today()
    all_problems: list[Problem] = []
    total = 0
    for f in args.files:
        path = Path(f)
        if not path.is_file():
            print(f"trivyignore_check: no such file: {f}", file=sys.stderr)
            return 2
        entries, problems = check_text(path.read_text(encoding="utf-8"), f, today, args.max_days)
        total += len(entries)
        all_problems.extend(problems)
        for e in entries:
            left = (e.expires - today).days if e.expires else None
            status = "expired" if left is not None and left < 0 else (f"{left} days left" if left is not None else "no expiry")
            print(f"{f}:{e.line}: {e.finding_id} exp:{e.expires.isoformat() if e.expires else '-'} ({status})")
    for p in all_problems:
        print(f"{p.path}:{p.line}: ERROR {p.rule} {p.message}")
    print(f"{total} entr{'y' if total == 1 else 'ies'} checked against {today.isoformat()}: {len(all_problems)} problem(s)")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
