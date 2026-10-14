#!/usr/bin/env python3
"""Rotation drill: prove the app picks up a rotated secret without a restart.

Runs entirely on this machine, against the real app (app/server.py) in a
subprocess:

  1. write v1 secret files the way the CSI driver lays them out: a
     timestamped directory, a `..data` symlink to it, and one symlink per
     file pointing through `..data`;
  2. start the app with SECRETS_DIR pointing there and wait until /healthz
     reports the v1 version;
  3. write v2 into a new timestamped directory, point a temporary symlink at
     it and rename it over `..data` (one atomic rename swaps every file at
     once, so the app can never read v2 username with v1 password);
  4. poll /healthz until it reports the v2 version, and print the timeline.

/healthz only ever returns a version fingerprint, so the drill compares
fingerprints and never sees or prints a value. At the end it also checks
the app's own log output for every v1 and v2 value.

Values are random, generated per run, and never written outside the
temporary directory, which is removed afterwards.

Exit status: 0 when v2 is observed within --timeout and the logs are clean,
1 otherwise, 2 if the app never became ready on v1.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
APP = PROJECT / "app" / "server.py"


def _load_app_module():
    spec = importlib.util.spec_from_file_location("secure_frontend_server", APP)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


server = _load_app_module()


def make_version(tag: str) -> dict[str, str]:
    return {
        "db-username": f"app_{tag}",
        "db-password": secrets.token_urlsafe(24),
        "db-host": f"db-{tag}.cluster-example.us-east-1.rds.amazonaws.com",
        "api-key": secrets.token_hex(20),
    }


def write_version(secrets_dir: Path, values: dict[str, str]) -> None:
    """Kubelet-style atomic writer: new dir, temp symlink, rename over ..data."""
    secrets_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"..{time.strftime('%Y_%m_%d_%H_%M_%S')}.{secrets.token_hex(4)}"
    target = secrets_dir / stamp
    target.mkdir()
    for name, value in values.items():
        (target / name).write_text(value)
    tmp_link = secrets_dir / "..data_tmp"
    if tmp_link.is_symlink():
        tmp_link.unlink()
    tmp_link.symlink_to(stamp)
    data_link = secrets_dir / "..data"
    old = os.readlink(data_link) if data_link.is_symlink() else None
    os.replace(tmp_link, data_link)
    for name in values:
        link = secrets_dir / name
        if not link.is_symlink():
            link.symlink_to(Path("..data") / name)
    if old:
        shutil.rmtree(secrets_dir / old, ignore_errors=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def healthz(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return json.loads(exc.read() or b"{}")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return None


@dataclass
class Result:
    ok: bool
    exit_code: int
    events: list[str] = field(default_factory=list)
    observed_after: float | None = None
    app_log: str = ""
    values: list[str] = field(default_factory=list)  # for the caller's own leak checks; never printed


def run_drill(timeout: float = 15.0, app_poll: float = 0.5, check_every: float = 0.1,
              out=sys.stdout) -> Result:
    start = time.monotonic()
    result = Result(ok=False, exit_code=1)

    def event(msg: str) -> None:
        line = f"t+{time.monotonic() - start:7.3f}s  {msg}"
        result.events.append(line)
        print(line, file=out, flush=True)

    workdir = Path(tempfile.mkdtemp(prefix="rotation-drill-"))
    secrets_dir = workdir / "secrets"
    v1, v2 = make_version("v1"), make_version("v2")
    result.values = list(v1.values()) + list(v2.values())
    fp1, fp2 = server.fingerprint(v1), server.fingerprint(v2)
    port = free_port()
    log_path = workdir / "app.log"
    proc = None
    try:
        write_version(secrets_dir, v1)
        event(f"wrote v1 secret files ({len(v1)} files, atomic ..data layout), expected version {fp1}")
        env = {"PATH": os.environ.get("PATH", ""), "SECRETS_DIR": str(secrets_dir), "PORT": str(port),
               "SECRETS_POLL_SECONDS": str(app_poll), "PYTHONUNBUFFERED": "1"}
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen([sys.executable, str(APP)], env=env, stdout=log_fh, stderr=subprocess.STDOUT)
        event(f"started app pid {proc.pid} on 127.0.0.1:{port} (file poll every {app_poll}s)")

        deadline = time.monotonic() + timeout
        h = None
        while time.monotonic() < deadline:
            h = healthz(port)
            if h and h.get("version") == fp1:
                break
            if proc.poll() is not None:
                break
            time.sleep(check_every)
        if not h or h.get("version") != fp1:
            event("FAIL app never reported v1 as loaded")
            result.exit_code = 2
            return result
        event(f"app ready: secrets_loaded={str(h['secrets_loaded']).lower()} version={h['version']}")

        write_version(secrets_dir, v2)
        swapped = time.monotonic()
        event(f"swapped in v2 (one rename of ..data), expected version {fp2}")

        polls, last_report = 0, swapped
        deadline = swapped + timeout
        while time.monotonic() < deadline:
            h = healthz(port)
            polls += 1
            if h and h.get("version") == fp2:
                result.observed_after = time.monotonic() - swapped
                event(f"app observed v2: version={h['version']} rotations={h['rotations']} "
                      f"({result.observed_after:.3f}s after the swap, {polls} polls)")
                break
            if time.monotonic() - last_report >= 1.0:
                last_report = time.monotonic()
                event(f"still on version={(h or {}).get('version')} after {polls} polls")
            time.sleep(check_every)
        else:
            event(f"FAIL v2 not observed within {timeout:.1f}s (last version {(h or {}).get('version')})")
            return result
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if log_path.exists():
            result.app_log = log_path.read_text()
        shutil.rmtree(workdir, ignore_errors=True)

    leaked = [v for v in result.values if v in result.app_log]
    lines = len(result.app_log.splitlines())
    if leaked:
        event(f"FAIL {len(leaked)} secret value(s) appeared in {lines} app log lines")
        return result
    event(f"log check: 0 of {len(result.values)} secret values in {lines} app log lines")
    result.ok, result.exit_code = True, 0
    print(f"PASS rotation observed {result.observed_after:.3f}s after the swap "
          f"(app poll {app_poll}s, timeout {timeout:.1f}s)", file=out)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Simulate a CSI-driver secret rotation against the local app.")
    p.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for each version (default 15)")
    p.add_argument("--app-poll", type=float, default=0.5,
                   help="SECRETS_POLL_SECONDS for the app (default 0.5; the chart uses 10)")
    args = p.parse_args(argv)
    result = run_drill(timeout=args.timeout, app_poll=args.app_poll)
    if not result.ok:
        print("FAIL rotation drill", file=sys.stdout)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
