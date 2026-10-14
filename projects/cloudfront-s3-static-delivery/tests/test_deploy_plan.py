"""Upload/delete sets, Cache-Control, ordering and invalidation (scripts/deploy_plan.py)."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from helpers import SAMPLE_BUILD, SAMPLE_MANIFEST
from deploy_plan import (
    CACHE_HTML,
    CACHE_IMMUTABLE,
    PlanError,
    build_plan,
    cache_control,
    content_type,
    invalidation_paths_for,
    is_hashed_asset,
    load_manifest,
    scan_build,
)

MD5_A = hashlib.md5(b"a").hexdigest()
MD5_B = hashlib.md5(b"b").hexdigest()


def keys(items):
    return [i["key"] for i in items]


class CacheControlTests(unittest.TestCase):
    def test_hashed_js_and_css_are_immutable(self):
        for key in ("assets/app.3f9a1c2e.js", "site.8d4e6f01.css", "a/b/c.0123456789abcdef.js"):
            with self.subTest(key=key):
                self.assertTrue(is_hashed_asset(key))
                self.assertEqual(cache_control(key), CACHE_IMMUTABLE)

    def test_short_or_non_hex_hash_is_not_hashed(self):
        for key in ("app.3f9a1c2.js", "app.ZZZZZZZZ.js", "app.min.js", "app.3f9a1c2e.json",
                    "app.3F9A1C2E.js", "assets.3f9a1c2e/app.js"):
            with self.subTest(key=key):
                self.assertFalse(is_hashed_asset(key))

    def test_html_is_no_cache(self):
        self.assertEqual(cache_control("index.html"), CACHE_HTML)
        self.assertEqual(cache_control("docs/INDEX.HTM"), CACHE_HTML)

    def test_others_get_short_ttl(self):
        self.assertEqual(cache_control("robots.txt"), "public, max-age=300")
        self.assertEqual(cache_control("img/logo.png", short_ttl=60), "public, max-age=60")

    def test_unhashed_css_gets_short_ttl(self):
        self.assertEqual(cache_control("styles.css"), "public, max-age=300")

    def test_content_types(self):
        self.assertEqual(content_type("index.html"), "text/html; charset=utf-8")
        self.assertEqual(content_type("a.js"), "text/javascript; charset=utf-8")
        self.assertEqual(content_type("a.svg"), "image/svg+xml; charset=utf-8")
        self.assertEqual(content_type("a.png"), "image/png")
        self.assertEqual(content_type("LICENSE"), "application/octet-stream")


class SetTests(unittest.TestCase):
    def test_new_file(self):
        plan = build_plan({"index.html": MD5_A}, {})
        self.assertEqual(plan["upload"][0]["reason"], "new")
        self.assertEqual(plan["delete"], [])

    def test_changed_file(self):
        plan = build_plan({"index.html": MD5_A}, {"index.html": MD5_B})
        self.assertEqual(plan["upload"][0]["reason"], "changed")

    def test_unchanged_file_skipped(self):
        plan = build_plan({"index.html": MD5_A}, {"index.html": MD5_A})
        self.assertEqual(plan["upload"], [])
        self.assertEqual(plan["summary"]["unchanged"], 1)
        self.assertEqual(plan["invalidation"]["paths"], [])

    def test_deleted_file(self):
        plan = build_plan({}, {"old.html": MD5_A})
        self.assertEqual(plan["delete"], ["old.html"])

    def test_multipart_etag_counts_as_changed(self):
        plan = build_plan({"video.mp4": MD5_A}, {"video.mp4": MD5_A[:32] + "-3"})
        self.assertEqual(plan["upload"][0]["reason"], "changed (remote ETag is not an MD5)")

    def test_upload_order_assets_then_other_then_html(self):
        local = {"index.html": MD5_A, "robots.txt": MD5_A, "app.3f9a1c2e.js": MD5_A, "a/index.html": MD5_A}
        plan = build_plan(local, {})
        self.assertEqual(keys(plan["upload"]), ["app.3f9a1c2e.js", "robots.txt", "a/index.html", "index.html"])
        self.assertEqual([u["phase"] for u in plan["upload"]], ["hashed-asset", "other", "html", "html"])

    def test_keep_old_hashed(self):
        remote = {"app.0b1c2d3e.js": MD5_A, "old.html": MD5_A}
        plan = build_plan({}, remote, keep_old_hashed=True)
        self.assertEqual(plan["delete"], ["old.html"])
        self.assertEqual(plan["retained"], ["app.0b1c2d3e.js"])
        self.assertEqual(build_plan({}, remote)["retained"], [])


class InvalidationTests(unittest.TestCase):
    def test_changed_html_invalidated_with_directory_form(self):
        plan = build_plan({"docs/index.html": MD5_A}, {"docs/index.html": MD5_B})
        self.assertEqual(plan["invalidation"]["paths"], ["/docs/index.html", "/docs/"])

    def test_root_index(self):
        self.assertEqual(invalidation_paths_for("index.html"), ["/index.html", "/"])

    def test_new_html_not_invalidated(self):
        plan = build_plan({"about/index.html": MD5_A}, {})
        self.assertEqual(plan["invalidation"]["paths"], [])

    def test_deleted_html_invalidated(self):
        plan = build_plan({}, {"pricing/index.html": MD5_A})
        self.assertEqual(plan["invalidation"]["paths"], ["/pricing/index.html", "/pricing/"])

    def test_hashed_assets_never_invalidated(self):
        plan = build_plan({"app.3f9a1c2e.js": MD5_A}, {"app.3f9a1c2e.js": MD5_B, "old.0b1c2d3e.css": MD5_A})
        self.assertEqual(plan["invalidation"]["paths"], [])

    def test_special_characters_encoded(self):
        self.assertEqual(invalidation_paths_for("files/a b&c.pdf"), ["/files/a%20b%26c.pdf"])

    def test_at_threshold_stays_per_path(self):
        remote = {f"p{i}.txt": MD5_B for i in range(15)}
        local = {k: MD5_A for k in remote}
        inv = build_plan(local, remote, threshold=15)["invalidation"]
        self.assertFalse(inv["wildcard"])
        self.assertEqual(len(inv["paths"]), 15)

    def test_above_threshold_collapses_to_wildcard(self):
        remote = {f"p{i}.txt": MD5_B for i in range(16)}
        local = {k: MD5_A for k in remote}
        plan = build_plan(local, remote, threshold=15)
        self.assertEqual(plan["invalidation"]["paths"], ["/*"])
        self.assertTrue(plan["invalidation"]["wildcard"])
        self.assertEqual(plan["invalidation"]["path_count"], 16)
        self.assertEqual(plan["summary"]["invalidation_paths"], 1)

    def test_directory_forms_count_toward_threshold(self):
        remote = {f"d{i}/index.html": MD5_B for i in range(3)}
        local = {k: MD5_A for k in remote}
        self.assertTrue(build_plan(local, remote, threshold=5)["invalidation"]["wildcard"])

    def test_bad_threshold(self):
        with self.assertRaises(PlanError):
            build_plan({}, {}, threshold=0)


class ManifestTests(unittest.TestCase):
    def test_plain_map_strips_quotes_and_case(self):
        self.assertEqual(load_manifest({"a": '"ABC"'}), {"a": "abc"})

    def test_object_map(self):
        self.assertEqual(load_manifest({"a": {"etag": MD5_A}}), {"a": MD5_A})

    def test_list_objects_v2_shape(self):
        data = {"Contents": [{"Key": "a", "ETag": f'"{MD5_A}"', "Size": 1}]}
        self.assertEqual(load_manifest(data), {"a": MD5_A})

    def test_empty_bucket_output(self):
        self.assertEqual(load_manifest({"RequestCharged": None, "Prefix": ""}), {})

    def test_bad_shapes(self):
        for bad in ([], {"a": 1}, {"a": {}}, {"Contents": [{"Key": "a"}]}, {"Contents": "x"}):
            with self.subTest(bad=bad), self.assertRaises(PlanError):
                load_manifest(bad)


class SampleBuildTests(unittest.TestCase):
    """Pins the README excerpt to the shipped sample."""

    @classmethod
    def setUpClass(cls):
        manifest = load_manifest(json.loads(SAMPLE_MANIFEST.read_text()))
        cls.plan = build_plan(scan_build(SAMPLE_BUILD), manifest)

    def test_sets(self):
        self.assertEqual(keys(self.plan["upload"]), [
            "assets/app.3f9a1c2e7b.js", "assets/site.8d4e6f01.css", "robots.txt",
            "about/index.html", "index.html"])
        self.assertEqual(self.plan["delete"],
                         ["assets/app.0b1c2d3e4f.js", "assets/site.1a2b3c4d.css", "pricing/index.html"])

    def test_invalidation(self):
        self.assertEqual(self.plan["invalidation"]["paths"],
                         ["/index.html", "/", "/pricing/index.html", "/pricing/", "/robots.txt"])

    def test_summary(self):
        self.assertEqual(self.plan["summary"], {
            "local_files": 8, "remote_objects": 8, "new": 3, "changed": 2, "unchanged": 3,
            "deleted": 3, "retained": 0, "invalidation_paths": 5})


class ScanTests(unittest.TestCase):
    def test_scan_uses_posix_keys_and_md5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "index.html").write_bytes(b"a")
            self.assertEqual(scan_build(root), {"docs/index.html": MD5_A})

    def test_missing_dir(self):
        with self.assertRaises(PlanError):
            scan_build(Path("/nonexistent/build"))


if __name__ == "__main__":
    unittest.main()
