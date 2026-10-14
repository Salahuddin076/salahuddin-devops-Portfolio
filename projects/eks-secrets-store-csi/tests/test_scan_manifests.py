"""scan_manifests.py: good and bad fixtures, each rule on its own, and the CLI contract."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import textwrap
import unittest
from contextlib import redirect_stdout

from helpers import FIXTURES, SCRIPTS_DIR

import scan_manifests
import yaml_lite

GOOD = FIXTURES / "manifests" / "good.yaml"
BAD = FIXTURES / "manifests" / "bad.yaml"


def rules(text):
    return sorted(f.rule for f in scan_manifests.scan_text(textwrap.dedent(text), "t"))


def deployment(container_extra="", pod_extra="automountServiceAccountToken: false", volumes=""):
    return f"""
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: d
    spec:
      template:
        metadata:
          labels:
            app: d
        spec:
          {pod_extra}
          containers:
            - name: c
              image: example/c:1.0.0
              {container_extra}
          {volumes}
    """


class FixtureTests(unittest.TestCase):
    def test_good_fixture_is_clean(self):
        self.assertEqual(scan_manifests.scan_text(GOOD.read_text(), "good"), [])

    def test_bad_fixture_hits_every_rule(self):
        found = scan_manifests.scan_text(BAD.read_text(), "bad")
        self.assertEqual(sorted({f.rule for f in found}),
                         ["SM001", "SM002", "SM003", "SM004", "SM005", "SM006", "SM007"])
        self.assertEqual(sum(f.severity == "error" for f in found), 8)
        self.assertEqual(sum(f.severity == "warning" for f in found), 3)

    def test_findings_never_print_a_value(self):
        text = "\n".join(f.text() for f in scan_manifests.scan_text(BAD.read_text(), "bad"))
        # The fixture's literal values, read back from the file itself.
        values = [line.split(": ", 1)[1].strip('"') for line in BAD.read_text().splitlines()
                  if line.strip().startswith(("value: ", "password: ", "username: "))]
        self.assertEqual(len(values), 5)
        for value in values:
            self.assertNotIn(value, text)


class RuleTests(unittest.TestCase):
    def test_sm001_secret_name_with_literal(self):
        self.assertEqual(rules(deployment("env: [{\"name\": \"API_KEY\", \"value\": \"abc\"}]")), ["SM001"])
        self.assertEqual(rules(deployment("env: [{\"name\": \"githubToken\", \"value\": \"abc\"}]")), ["SM001"])

    def test_sm001_reference_names_and_empty_values_pass(self):
        for name in ("DB_PASSWORD_FILE", "SECRETS_DIR", "API_KEY_PATH", "TOKEN_URL", "SECRETS_POLL_SECONDS"):
            with self.subTest(name=name):
                self.assertEqual(rules(deployment(f"env: [{{\"name\": \"{name}\", \"value\": \"/x\"}}]")), [])
        self.assertEqual(rules(deployment("env: [{\"name\": \"DB_PASSWORD\", \"value\": \"\"}]")), [])

    def test_sm002_value_looks_like_a_credential(self):
        key = "AKIA" + "Q" * 16
        self.assertEqual(rules(deployment(f"env: [{{\"name\": \"UPSTREAM\", \"value\": \"{key}\"}}]")), ["SM002"])
        self.assertEqual(rules(deployment("env: [{\"name\": \"COLOR\", \"value\": \"blue-and-green-theme\"}]")), [])

    def test_sm003_secret_with_literal_data_only(self):
        self.assertEqual(rules("kind: Secret\nmetadata: {\"name\": \"s\"}\nstringData: {\"k\": \"v\"}\n"), ["SM003"])
        self.assertEqual(rules("kind: Secret\nmetadata: {\"name\": \"s\"}\ntype: Opaque\n"), [])

    def test_sm004_volume_and_mount_must_be_read_only(self):
        vol = 'volumes: [{"name": "s", "csi": {"driver": "secrets-store.csi.k8s.io", "readOnly": true}}]'
        ok = deployment('volumeMounts: [{"name": "s", "mountPath": "/mnt/secrets", "readOnly": true}]', volumes=vol)
        self.assertEqual(rules(ok), [])
        rw_mount = deployment('volumeMounts: [{"name": "s", "mountPath": "/mnt/secrets"}]', volumes=vol)
        self.assertEqual(rules(rw_mount), ["SM004"])
        rw_vol = deployment('volumeMounts: [{"name": "s", "mountPath": "/m", "readOnly": true}]',
                            volumes=vol.replace("true", "false"))
        self.assertEqual(rules(rw_vol), ["SM004"])

    def test_sm005_token_automount(self):
        self.assertEqual(rules(deployment(pod_extra="serviceAccountName: x")), ["SM005"])
        sa_off = "kind: ServiceAccount\nmetadata: {\"name\": \"x\"}\nautomountServiceAccountToken: false\n---\n"
        # The pod inherits the SA's false.
        self.assertEqual(rules(sa_off + textwrap.dedent(deployment(pod_extra="serviceAccountName: x"))), [])
        # The pod's own true overrides the SA's false.
        self.assertEqual(rules(sa_off + textwrap.dedent(deployment(
            pod_extra="serviceAccountName: x\n          automountServiceAccountToken: true"))), ["SM005"])

    def test_sm005_justification_annotation(self):
        sa = ("kind: ServiceAccount\nmetadata:\n  name: x\n  annotations:\n"
              "    secrets.example.com/kube-api-token-justification: \"reads ConfigMaps via the API\"\n")
        self.assertEqual(rules(sa), [])

    def test_sm006_env_from_secret_is_a_warning(self):
        found = scan_manifests.scan_text(textwrap.dedent(deployment(
            'envFrom: [{"secretRef": {"name": "s"}}]')), "t")
        self.assertEqual([(f.rule, f.severity) for f in found], [("SM006", "warning")])

    def test_cronjob_and_list_are_walked(self):
        cron = """
        apiVersion: v1
        kind: List
        items:
          - kind: CronJob
            metadata:
              name: cj
            spec:
              jobTemplate:
                spec:
                  template:
                    spec:
                      automountServiceAccountToken: false
                      containers:
                        - name: c
                          env:
                            - name: ADMIN_PASSWORD
                              value: "letmein123"
        """
        self.assertEqual(rules(cron), ["SM001"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(SCRIPTS_DIR / "scan_manifests.py"), *args],
                              input=stdin, capture_output=True, text=True, timeout=30, check=False)

    def test_exit_codes(self):
        self.assertEqual(self.run_cli(str(GOOD)).returncode, 0)
        self.assertEqual(self.run_cli(str(BAD)).returncode, 1)
        self.assertEqual(self.run_cli("/nonexistent.yaml").returncode, 2)

    def test_stdin_and_fail_on_warning(self):
        warn_only = textwrap.dedent(deployment('envFrom: [{"secretRef": {"name": "s"}}]'))
        self.assertEqual(self.run_cli("-", stdin=warn_only).returncode, 0)
        self.assertEqual(self.run_cli("-", "--fail-on", "warning", stdin=warn_only).returncode, 1)

    def test_json_format(self):
        out = json.loads(self.run_cli(str(BAD), "--format", "json").stdout)
        self.assertEqual((out["objects"], out["errors"], out["warnings"]), (4, 8, 3))

    def test_main_summary_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(scan_manifests.main([str(GOOD)]), 0)
        self.assertEqual(buf.getvalue().strip().splitlines()[-1],
                         "scan_manifests: 4 objects, 0 error(s), 0 warning(s)")


class YamlLiteTests(unittest.TestCase):
    def test_block_scalars_and_flow(self):
        docs = yaml_lite.load_all(textwrap.dedent("""\
            a: |
              line one
                indented
            b: >-
              folded
              text
            c: [1, "two"]
            d:
              - x: 1
                y: 'it''s'
              - plain
            ---
            # comment-only doc is skipped
            ---
            e: "#not a comment"  # but this is
            """))
        self.assertEqual(docs[0], {"a": "line one\n  indented\n", "b": "folded text", "c": [1, "two"],
                                   "d": [{"x": 1, "y": "it's"}, "plain"]})
        self.assertEqual(docs[1], {"e": "#not a comment"})

    def test_bad_indentation_raises(self):
        with self.assertRaises(ValueError):
            yaml_lite.load_all("a: 1\n   b: 2\n")


if __name__ == "__main__":
    unittest.main()
