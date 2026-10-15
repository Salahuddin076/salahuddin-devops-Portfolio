"""promtool check/test rules in the pinned Prometheus image.

Runs only when docker is available AND the image is already present locally
(the unit tests never pull images). CI runs promtool in its own job.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest

from helpers import PROJECT, PROMETHEUS_IMAGE

DOCKER = shutil.which("docker")


def image_present() -> bool:
    if DOCKER is None:
        return False
    try:
        return subprocess.run([DOCKER, "image", "inspect", PROMETHEUS_IMAGE], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def promtool(*args):
    return subprocess.run([DOCKER, "run", "--rm", "--network", "none", "-v", f"{PROJECT}:/work:ro", "-w", "/work",
                           "--entrypoint", "promtool", PROMETHEUS_IMAGE, *args],
                          capture_output=True, text=True, timeout=300)


@unittest.skipUnless(image_present(), f"docker or {PROMETHEUS_IMAGE} not available locally")
class PromtoolTests(unittest.TestCase):
    def test_check_rules(self):
        files = sorted(p.relative_to(PROJECT).as_posix() for p in (PROJECT / "generated" / "prometheus").glob("*.yml"))
        proc = promtool("check", "rules", *files)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.count("SUCCESS"), 4)

    def test_unit_tests(self):
        proc = promtool("test", "rules", "tests/promtool/slo-alerts.test.yml")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("SUCCESS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
