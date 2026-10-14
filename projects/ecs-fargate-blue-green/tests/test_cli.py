"""CLI smoke tests through subprocess: exit codes and output shape."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, PROJECT, SCRIPTS_DIR, VALUES_EXAMPLE


def run(script, *args, cwd=PROJECT):
    return subprocess.run([sys.executable, str(SCRIPTS_DIR / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=60, check=False)


class SimulatorCliTests(unittest.TestCase):
    def test_canary_with_alarm(self):
        proc = run("traffic_shift_sim.py", "--config", "CodeDeployDefault.ECSCanary10Percent5Minutes",
                   "--minutes", "20", "--alarm-at", "3", "--termination-wait", "10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("result: ROLLED_BACK at minute 3", proc.stdout)

    def test_json(self):
        proc = run("traffic_shift_sim.py", "--config", "CodeDeployDefault.ECSAllAtOnce", "--minutes", "2", "--json")
        self.assertEqual(json.loads(proc.stdout)["outcome"], "SUCCEEDED")

    def test_bad_config_exits_2(self):
        proc = run("traffic_shift_sim.py", "--config", "CodeDeployDefault.OneAtATime", "--minutes", "5")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unrecognised deployment config", proc.stderr)


class PolicyCliTests(unittest.TestCase):
    def test_default_files_pass(self):
        proc = run("check_bluegreen_policy.py")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("3/3 environment file(s) passed", proc.stdout)

    def test_bad_fixtures_fail(self):
        proc = run("check_bluegreen_policy.py", *sorted(FIXTURES.glob("bad-*.json")))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("0/9 environment file(s) passed", proc.stdout)

    def test_json_output(self):
        proc = run("check_bluegreen_policy.py", FIXTURES / "bad-zero-termination.json", "--json")
        self.assertEqual(json.loads(proc.stdout)[0]["findings"][0]["rule"], "BG004")

    def test_works_from_another_directory(self):
        proc = run("check_bluegreen_policy.py", cwd=PROJECT.parent)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class RenderCliTests(unittest.TestCase):
    def test_writes_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run("render_appspec.py", "--values", VALUES_EXAMPLE, "--out-dir", tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((Path(tmp) / "appspec.yaml").is_file())
            json.loads((Path(tmp) / "taskdef.json").read_text())
            self.assertIn("image tag: 3f9c2b1e", proc.stdout)

    def test_latest_exits_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run("render_appspec.py", "--values", VALUES_EXAMPLE, "--out-dir", tmp,
                       "--set", "IMAGE=123456789012.dkr.ecr.us-east-1.amazonaws.com/bluegreen-api:latest")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("mutable tag 'latest'", proc.stderr)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_values_file_exits_2(self):
        self.assertEqual(run("render_appspec.py", "--values", "/nonexistent.json").returncode, 2)


class HookPackagingTests(unittest.TestCase):
    def test_hook_modules_import_without_boto3_installed_path(self):
        code = ("import sys; sys.modules['boto3'] = None; sys.path.insert(0, 'src/hooks'); "
                "import before_allow_traffic, after_allow_traffic; print('ok')")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=PROJECT,
                              timeout=60, check=False)
        self.assertEqual(proc.stdout.strip(), "ok", proc.stderr)


if __name__ == "__main__":
    unittest.main()
