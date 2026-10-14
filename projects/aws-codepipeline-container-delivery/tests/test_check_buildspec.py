import glob
import io
import os
import unittest
from contextlib import redirect_stdout

import helpers

import check_buildspec as cb

REAL_BUILDSPECS = sorted(glob.glob(os.path.join(helpers.BUILDSPEC_DIR, "*.yml")))


def fixture(name):
    return os.path.join(helpers.FIXTURES_DIR, name)


def rules(path):
    return sorted({f.rule for f in cb.check_file(path)})


class RealBuildspecTests(unittest.TestCase):
    def test_both_buildspecs_exist(self):
        names = [os.path.basename(p) for p in REAL_BUILDSPECS]
        self.assertEqual(names, ["buildspec-build.yml", "buildspec-test.yml"])

    def test_real_buildspecs_pass(self):
        for path in REAL_BUILDSPECS:
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(cb.check_file(path), [])

    def test_build_buildspec_parsed_as_expected(self):
        with open(os.path.join(helpers.BUILDSPEC_DIR, "buildspec-build.yml"), encoding="utf-8") as handle:
            doc = cb.parse_yaml_subset(handle.read())
        secrets = doc["env"]["secrets-manager"]
        self.assertTrue(all(":" in v for v in secrets.values()))
        self.assertEqual(doc["artifacts"]["files"], ["imagedefinitions.json"])
        self.assertEqual(doc["reports"]["image-scan"]["file-format"], "JUNITXML")
        commands = cb._commands(doc)
        self.assertTrue(any("trivy image" in c and "--exit-code 1" in c for c in commands))

    def test_default_files_and_exit_code(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cb.main([]), 0)
        self.assertIn("2/2 buildspec file(s) passed", out.getvalue())


class FixtureTests(unittest.TestCase):
    def test_good_fixture_passes(self):
        self.assertEqual(rules(fixture("good-build.yml")), [])

    def test_bad_fixtures_fail_with_expected_rules(self):
        expected = {
            "bad-plaintext-secret.yml": ["BS002"],
            "bad-secret-no-json-key.yml": ["BS003"],
            "bad-no-reports.yml": ["BS001", "BS004"],
            "bad-latest-tag.yml": ["BS005"],
            "bad-build-number-tag.yml": ["BS005"],
            "bad-no-trivy.yml": ["BS006"],
            "bad-push-before-scan.yml": ["BS007"],
            "bad-unparseable.yml": ["BS000"],
        }
        on_disk = sorted(os.path.basename(p) for p in glob.glob(fixture("bad-*.yml")))
        self.assertEqual(on_disk, sorted(expected))
        for name, want in expected.items():
            with self.subTest(fixture=name):
                self.assertEqual(rules(fixture(name)), want)

    def test_cli_fails_on_bad_fixture(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cb.main([fixture("bad-plaintext-secret.yml")]), 1)
        self.assertIn("FAIL", out.getvalue())
        self.assertIn("DB_PASSWORD", out.getvalue())


class SecretReferenceTests(unittest.TestCase):
    def test_json_key_detection(self):
        good = [
            "prod/db:password",
            "prod/db:password:AWSCURRENT",
            "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod/db-AbCdEf:password",
            "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod/db-AbCdEf:password::",
        ]
        bad = [
            "prod/db",
            "prod/db:",
            "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod/db-AbCdEf",
            "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod/db-AbCdEf:",
            "",
        ]
        for ref in good:
            with self.subTest(ref=ref):
                self.assertTrue(cb._secret_ref_has_json_key(ref))
        for ref in bad:
            with self.subTest(ref=ref):
                self.assertFalse(cb._secret_ref_has_json_key(ref))


class ParserTests(unittest.TestCase):
    def test_comments_quotes_and_colons(self):
        doc = cb.parse_yaml_subset(
            "version: 0.2  # trailing comment\n"
            "env:\n"
            "  variables:\n"
            "    URL: \"https://example.com/#anchor\"\n"
            "phases:\n"
            "  build:\n"
            "    commands:\n"
            "      - echo \"a: b\" # not stripped from commands\n"
            "      - 'quoted command'\n"
        )
        self.assertEqual(doc["version"], "0.2")
        self.assertEqual(doc["env"]["variables"]["URL"], "https://example.com/#anchor")
        self.assertEqual(
            doc["phases"]["build"]["commands"], ['echo "a: b" # not stripped from commands', "quoted command"]
        )

    def test_sequence_at_same_indent_as_key(self):
        doc = cb.parse_yaml_subset("artifacts:\n  files:\n  - a.json\n  - b.json\n")
        self.assertEqual(doc["artifacts"]["files"], ["a.json", "b.json"])

    def test_rejects_unsupported_constructs(self):
        for text in ("a: [1, 2]\n", "a: |\n  text\n", "a: 1\na: 2\n", "a:\n\tb: 1\n", "a: 1\n   b: 2\n"):
            with self.subTest(text=text), self.assertRaises(cb.ParseError):
                cb.parse_yaml_subset(text)

    def test_secret_name_heuristic(self):
        for name in ("DB_PASSWORD", "api_key", "GITHUB_TOKEN", "CLIENT_SECRET", "AWS_ACCESS_KEY_ID"):
            self.assertRegex(name, cb.SECRET_NAME_RE)
        for name in ("IMAGE_TAG", "REPORT_DIR", "TRIVY_VERSION", "PYTHONDONTWRITEBYTECODE"):
            self.assertNotRegex(name, cb.SECRET_NAME_RE)


if __name__ == "__main__":
    unittest.main()
