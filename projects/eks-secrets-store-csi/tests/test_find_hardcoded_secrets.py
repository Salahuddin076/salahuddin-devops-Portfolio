"""find_hardcoded_secrets.py: true positives, false positives, the allowlist, and this project.

The test cases are, by necessity, lines that look like hard-coded
credentials, so this file is the second entry in .secrets-allowlist. Every
value is synthetic; the AWS-shaped ones are assembled at run time.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from helpers import PROJECT, SCRIPTS_DIR

import find_hardcoded_secrets as fhs

FAKE_KEY_ID = "AKIA" + "Z7QW3ERT5YUI9OPL"
FAKE_SECRET = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
TOKEN = "q8Zr4LmP2vXw" + "9TbK7nYc3HdF6sJa1GeU"


def rules(line):
    return [r for r, _ in fhs.scan_line(line)]


class TruePositiveTests(unittest.TestCase):
    def test_aws_access_key_id(self):
        self.assertEqual(rules(f'key_id = "{FAKE_KEY_ID}"'), ["HS001"])
        self.assertEqual(rules(f"export X={FAKE_KEY_ID}"), ["HS001"])

    def test_aws_secret_access_key(self):
        self.assertEqual(rules(f"aws_secret_access_key = {FAKE_SECRET}"), ["HS002"])
        self.assertEqual(rules(f'AWS_SECRET_ACCESS_KEY: "{FAKE_SECRET}"'), ["HS002"])

    def test_private_key_header(self):
        self.assertEqual(rules(PEM), ["HS003"])
        self.assertEqual(rules("-----BEGIN " + "OPENSSH PRIVATE KEY-----"), ["HS003"])

    def test_password_style_assignments(self):
        for line in ('password = "hunter22"', "DB_PASSWORD='S3cure!pass'", '"apiKey": "abc123xyz"',
                     'client_secret := "s3cr3t-value"', 'self.auth_token = "tok-12345"'):
            with self.subTest(line=line):
                self.assertEqual(rules(line), ["HS004"])

    def test_high_entropy_string(self):
        self.assertEqual(rules(f'SIGNATURE_SEED = "{TOKEN}"'), ["HS005"])
        self.assertEqual(rules(f'x = "{"a3f9c2e17b4d8f6091ac3e5b7d9f1a2c"}"'), ["HS005"])

    def test_output_is_masked(self):
        details = " ".join(d for _, d in fhs.scan_line(f'password = "{TOKEN}"'))
        self.assertNotIn(TOKEN, details)
        self.assertIn("q8Zr...<32 chars>", details)


class FalsePositiveTests(unittest.TestCase):
    def test_references_and_placeholders_pass(self):
        for line in ('password = os.environ["DB_PASSWORD"]', 'password = "${DB_PASSWORD}"',
                     'password: "{{ .Values.db.password }}"', 'api_key = "<your-api-key>"',
                     'DB_PASSWORD_FILE = "/mnt/secrets/db-password"', 'secret_arn = "arn:aws:secretsmanager:x"',
                     'token = "example-token-value"', 'password = ""', 'password = "short"',
                     'SECRETS_DIR = "/mnt/secrets"', 'f\'password = "{password}"\'', 'db_secret_name = "secure-frontend/db-credentials"'):
            with self.subTest(line=line):
                self.assertEqual(rules(line), [])

    def test_ordinary_long_strings_pass(self):
        for line in ('name = "secure-frontend-db-credentials"', 'msg = "This_is_just_a_long_identifier"',
                     'image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/secure-frontend"',
                     'uses = "actions/checkout"', 'k = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"'):
            with self.subTest(line=line):
                self.assertEqual(rules(line), [])


class TreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text(f'KEY = "{FAKE_KEY_ID}"\nok = 1\n')
        (self.root / "fixtures").mkdir()
        (self.root / "fixtures" / "fake.env").write_text('password = "hunter22"\n')
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text(f"{FAKE_KEY_ID}\n")
        (self.root / "blob.bin").write_bytes(b"\0" + FAKE_KEY_ID.encode())

    def test_scans_text_skips_git_and_binaries(self):
        findings, scanned = fhs.scan_tree(self.root, fhs.Allowlist([], []))
        self.assertEqual(scanned, 2)
        self.assertEqual([(f.path, f.line, f.rule) for f in findings],
                         [("fixtures/fake.env", 1, "HS004"), ("src/app.py", 1, "HS001")])

    def test_allowlist_path_and_regex(self):
        al = self.root / ".secrets-allowlist"
        al.write_text("# comment\npath:fixtures/* # test data\nregex:^KEY = # vendored sample\n")
        findings, _ = fhs.scan_tree(self.root, fhs.Allowlist.load(al))
        self.assertEqual(findings, [])

    def test_allowlist_entry_without_reason_is_rejected(self):
        al = self.root / ".secrets-allowlist"
        al.write_text("path:fixtures/*\n")
        with self.assertRaises(ValueError):
            fhs.Allowlist.load(al)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(fhs.main([str(self.root)]), 2)

    def test_cli_exit_codes_and_no_full_value_in_output(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "find_hardcoded_secrets.py"), str(self.root)],
                              capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn(FAKE_KEY_ID, proc.stdout)
        self.assertIn("2 finding(s)", proc.stdout)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(fhs.main([str(self.root / "missing")]), 2)


class ThisProjectTests(unittest.TestCase):
    def test_project_is_clean_with_its_allowlist(self):
        findings, scanned = fhs.scan_tree(PROJECT, fhs.Allowlist.load(PROJECT / ".secrets-allowlist"))
        self.assertGreater(scanned, 20)
        self.assertEqual([f.text() for f in findings], [])

    def test_allowlist_only_covers_the_deliberate_fixture(self):
        al = fhs.Allowlist.load(PROJECT / ".secrets-allowlist")
        self.assertEqual(al.globs, ["tests/fixtures/manifests/bad.yaml", "tests/test_find_hardcoded_secrets.py"])
        self.assertEqual(al.patterns, [])
        # And without it, that fixture is exactly what's found.
        findings, _ = fhs.scan_tree(PROJECT, fhs.Allowlist([], []))
        self.assertEqual({f.path for f in findings},
                         {"tests/fixtures/manifests/bad.yaml", "tests/test_find_hardcoded_secrets.py"})


if __name__ == "__main__":
    unittest.main()
