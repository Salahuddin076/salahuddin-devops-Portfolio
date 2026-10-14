"""Every complete `$ python3 policy/...` sample in the README is real output.

Blocks elided with a "..." line (and the bad-fixture check_scps block,
whose JSON error text depends on the Python version) are skipped.
"""

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT

BLOCK = re.compile(r"```text\n(\$ python3 policy/[^\n]+)\n(.*?)\n```", re.S)


def samples():
    text = (PROJECT / "README.md").read_text()
    for command, body in BLOCK.findall(text):
        if "\n...\n" in f"\n{body}\n":
            continue
        yield command[2:], body


class ReadmeSampleTests(unittest.TestCase):
    def test_samples_found(self):
        commands = [c for c, _ in samples()]
        self.assertGreaterEqual(len([c for c in commands if "simulate_scp.py" in c]), 6)
        self.assertGreaterEqual(len([c for c in commands if "cidr_plan.py" in c]), 2)
        self.assertTrue(any("check_scps.py" in c for c in commands))

    def test_samples_match_real_output(self):
        for command, expected in samples():
            with self.subTest(command=command):
                argv = shlex.split(command)
                proc = subprocess.run([sys.executable, *argv[1:]], capture_output=True, text=True,
                                      cwd=PROJECT, timeout=60)
                actual = f"{proc.stdout.rstrip()}\n(exit {proc.returncode})"
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
