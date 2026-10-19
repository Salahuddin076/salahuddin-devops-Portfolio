"""compatibility_check.py: the per-service ARM64 compatibility manifest linter."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from helpers import DOCS_DIR, FIXTURES

import compatibility_check as cc

GOOD = FIXTURES / "compatibility" / "good.yaml"
BAD = FIXTURES / "compatibility" / "bad.yaml"


def run(path, fail_on="error"):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cc.main([str(path), "--fail-on", fail_on])
    return code, buf.getvalue()


class GoodFixtureTests(unittest.TestCase):
    def test_clean_at_error(self):
        code, out = run(GOOD)
        self.assertEqual(code, 0)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_clean_at_warning(self):
        code, _ = run(GOOD, fail_on="warning")
        self.assertEqual(code, 0)


class BadFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = cc.load_manifest(BAD)
        cls.report = cc.check_manifest(cls.doc)
        cls.rules = sorted({f.rule for f in cls.report.findings})

    def test_exit_code_and_counts(self):
        code, out = run(BAD, fail_on="warning")
        self.assertEqual(code, 1)
        self.assertIn("6 error(s), 2 warning(s)", out)

    def test_every_rule_fires(self):
        self.assertEqual(self.rules, [f"GC00{n}" for n in range(1, 9)])

    def test_gc001_missing_platform(self):
        f = next(x for x in self.report.findings if x.rule == "GC001")
        self.assertEqual(f.service, "legacy-batch")
        self.assertIn("linux/arm64", f.message)

    def test_gc002_unpinned_base_image(self):
        f = next(x for x in self.report.findings if x.rule == "GC002")
        self.assertEqual(f.service, "legacy-batch")
        self.assertIn("ubuntu:22.04", f.message)

    def test_gc003_invalid_scan_status(self):
        f = next(x for x in self.report.findings if x.rule == "GC003")
        self.assertIn("unknown", f.message)

    def test_gc004_promoted_without_passing_scan(self):
        f = next(x for x in self.report.findings if x.rule == "GC004")
        self.assertEqual(f.service, "image-resizer")
        self.assertIn("canary", f.message)

    def test_gc005_pass_with_findings(self):
        f = next(x for x in self.report.findings if x.rule == "GC005")
        self.assertIn("critical=1", f.message)

    def test_gc006_qemu_warning(self):
        f = next(x for x in self.report.findings if x.rule == "GC006")
        self.assertEqual(f.severity, "warning")

    def test_gc007_qemu_with_native_modules_is_an_error(self):
        f = next(x for x in self.report.findings if x.rule == "GC007")
        self.assertEqual(f.severity, "error")
        self.assertIn("pillow", f.message)

    def test_gc008_runtime_mismatch_without_note(self):
        f = next(x for x in self.report.findings if x.rule == "GC008")
        self.assertIn("3.11.6", f.message)
        self.assertIn("3.12.1", f.message)

    def test_fail_on_error_ignores_warnings_only_findings(self):
        # A manifest with only warning-level findings must pass --fail-on error.
        doc = {
            "services": {
                "svc": {
                    "rollout": {"stage": "design"},
                    "platforms": {
                        "linux/amd64": {
                            "base_image": "x@sha256:" + "a" * 64,
                            "build_method": "qemu",
                            "runtime_version": "1.0",
                            "native_modules": [],
                            "image_scan": {"status": "pass", "critical": 0, "high": 0},
                        },
                        "linux/arm64": {
                            "base_image": "x@sha256:" + "b" * 64,
                            "build_method": "qemu",
                            "runtime_version": "1.0",
                            "native_modules": [],
                            "image_scan": {"status": "pass", "critical": 0, "high": 0},
                        },
                    },
                }
            }
        }
        report = cc.check_manifest(doc)
        self.assertEqual([f.rule for f in report.findings], ["GC006", "GC006"])
        self.assertEqual(report.at_or_above("error"), [])
        self.assertEqual(len(report.at_or_above("warning")), 2)


class RuntimeVersionNoteTests(unittest.TestCase):
    def test_note_suppresses_gc008(self):
        base_platform = {
            "build_method": "native",
            "native_modules": [],
            "image_scan": {"status": "pass", "critical": 0, "high": 0},
        }
        doc = {
            "services": {
                "svc": {
                    "rollout": {"stage": "design"},
                    "runtime_version_note": "arm64 image ships a newer patch release deliberately",
                    "platforms": {
                        "linux/amd64": {**base_platform, "base_image": "x@sha256:" + "a" * 64, "runtime_version": "1.0.0"},
                        "linux/arm64": {**base_platform, "base_image": "x@sha256:" + "b" * 64, "runtime_version": "1.0.1"},
                    },
                }
            }
        }
        report = cc.check_manifest(doc)
        self.assertEqual(report.findings, [])


class ManifestErrorTests(unittest.TestCase):
    def test_missing_services_key_raises(self):
        with self.assertRaises(cc.ManifestError):
            cc.check_manifest({"not_services": {}})

    def test_main_returns_2_on_bad_path(self):
        code, _ = run("/no/such/file.yaml")
        self.assertEqual(code, 2)


class RealManifestTests(unittest.TestCase):
    """The shared docs/compatibility-manifest.yaml must itself be clean."""

    def test_docs_manifest_is_clean(self):
        code, out = run(DOCS_DIR / "compatibility-manifest.yaml", fail_on="warning")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
