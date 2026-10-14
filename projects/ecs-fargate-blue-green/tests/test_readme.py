"""Every `$ python3 scripts/...` sample in the README is real output.

Blocks whose command writes files (`--out-dir`) are skipped; the CLI tests
cover writing. stdout and stderr are compared together, then the exit code.
"""

import re
import shlex
import subprocess
import sys
import unittest

from helpers import PROJECT

BLOCK = re.compile(r"```text\n(\$ python3 scripts/[^\n]+)\n(.*?)\n```", re.S)


def samples():
    for command, body in BLOCK.findall((PROJECT / "README.md").read_text()):
        if "--out-dir" in command:
            continue
        yield command[2:], body


class ReadmeSampleTests(unittest.TestCase):
    def test_samples_found(self):
        commands = [c for c, _ in samples()]
        self.assertGreaterEqual(len([c for c in commands if "traffic_shift_sim.py" in c]), 3)
        self.assertGreaterEqual(len([c for c in commands if "check_bluegreen_policy.py" in c]), 2)
        self.assertGreaterEqual(len([c for c in commands if "render_appspec.py" in c]), 2)

    def test_samples_match_real_output(self):
        for command, expected in samples():
            with self.subTest(command=command):
                argv = shlex.split(command)
                proc = subprocess.run([sys.executable, *argv[1:]], capture_output=True, text=True,
                                      cwd=PROJECT, timeout=60, check=False)
                out = "\n".join(x for x in (proc.stdout.rstrip(), proc.stderr.rstrip()) if x)
                self.assertEqual(f"{out}\n(exit {proc.returncode})", expected)


if __name__ == "__main__":
    unittest.main()
