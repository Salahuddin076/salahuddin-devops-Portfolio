"""Docs stay honest: every CLI sample is real output, and the labels are right.

Each file's `$ PYTHONPATH=src python3 -m failover ...` blocks run in order in
one fresh directory (so `--fake-world` and `.failover/` carry over between
blocks of the same file, as they would for a reader). stdout and stderr are
compared together, then the exit code. Run IDs embed the wall-clock time,
so timestamps are normalised on both sides.
"""

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from helpers import PROJECT, SRC_DIR

BLOCK = re.compile(r"```text\n\$ PYTHONPATH=src python3 -m failover ([^\n]+)\n(.*?)\n```", re.S)
RUN_TS = re.compile(r"\d{8}T\d{6}Z")
CLASSIFICATION = ("Reference implementation of a pattern used in production work; all names, accounts "
                  "and values are synthetic. No production RTO/RPO figures are claimed.")
DOC_FILES = ["README.md", "runbooks/planned-failover.md", "runbooks/unplanned-failover.md",
             "runbooks/failback.md", "runbooks/game-day.md"]


def normalise(text):
    return RUN_TS.sub("<ts>", text)


class CliSampleTests(unittest.TestCase):
    def test_samples_match_real_output(self):
        env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
        for name in DOC_FILES:
            samples = BLOCK.findall((PROJECT / name).read_text())
            self.assertGreaterEqual(len(samples), 2, name)
            with tempfile.TemporaryDirectory() as cwd:
                for args, expected in samples:
                    with self.subTest(file=name, args=args):
                        proc = subprocess.run([sys.executable, "-m", "failover", *shlex.split(args)],
                                              capture_output=True, text=True, cwd=cwd, env=env,
                                              timeout=60, check=False)
                        out = "\n".join(x for x in (proc.stdout.rstrip(), proc.stderr.rstrip()) if x)
                        self.assertEqual(normalise(f"{out}\n(exit {proc.returncode})"), normalise(expected))


class LabelAndHygieneTests(unittest.TestCase):
    def test_readme_classification_line(self):
        self.assertIn(CLASSIFICATION, (PROJECT / "README.md").read_text())

    def test_runbooks_call_durations_targets(self):
        for name in DOC_FILES[1:]:
            text = (PROJECT / name).read_text()
            with self.subTest(name):
                flat = " ".join(text.replace(">", " ").split()).lower()
                self.assertIn("targets to measure", flat)

    def test_required_docs_exist(self):
        for rel in ["docs/architecture.md", "docs/operations.md", "docs/security.md", "docs/cost.md",
                    "docs/decisions/0001-warm-standby-vs-active-active.md",
                    "docs/decisions/0002-managed-switchover-vs-detach-promote.md",
                    "docs/decisions/0003-valkey-rebuildable.md",
                    "docs/decisions/0004-terraform-layout.md",
                    "docs/decisions/0005-fencing-before-promotion.md"]:
            with self.subTest(rel):
                self.assertTrue((PROJECT / rel).is_file())
        arch = (PROJECT / "docs" / "architecture.md").read_text()
        self.assertGreaterEqual(arch.count("```mermaid"), 4)
        self.assertIn("sequenceDiagram", arch)
        self.assertIn("approximate", (PROJECT / "docs" / "cost.md").read_text().lower())

    def test_no_placeholder_markers_or_empty_files(self):
        marker = re.compile(r"\b(" + "TO" + "DO|FIX" + "ME|XX" + "X)\b")
        for p in PROJECT.rglob("*"):
            if not p.is_file() or ".terraform" in p.parts or "__pycache__" in p.parts:
                continue
            with self.subTest(str(p.relative_to(PROJECT))):
                self.assertGreater(p.stat().st_size, 0)
                if p.suffix in (".py", ".md", ".tf", ".yaml", ".yml", ".json", ".tpl", ".txt", ".tftpl"):
                    self.assertIsNone(marker.search(p.read_text()))


if __name__ == "__main__":
    unittest.main()
