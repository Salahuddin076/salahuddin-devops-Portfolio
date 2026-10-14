"""The URI rewrite specification (scripts/rewrite.py)."""

import unittest

import helpers  # noqa: F401  (import path)
from rewrite import build_query_string, decide, handler, make_event


def run(uri, query=""):
    return handler(make_event(uri, query))


class DirectoryRewriteTests(unittest.TestCase):
    def test_root_becomes_index(self):
        self.assertEqual(run("/")["uri"], "/index.html")

    def test_trailing_slash_becomes_index(self):
        self.assertEqual(run("/docs/")["uri"], "/docs/index.html")

    def test_nested_directory(self):
        self.assertEqual(run("/docs/guides/setup/")["uri"], "/docs/guides/setup/index.html")

    def test_rewrite_keeps_query_string_untouched(self):
        result = run("/docs/", "page=2")
        self.assertEqual(result["uri"], "/docs/index.html")
        self.assertEqual(result["querystring"], {"page": {"value": "2"}})

    def test_rewrite_returns_request_not_response(self):
        self.assertNotIn("statusCode", run("/docs/"))
        self.assertEqual(run("/docs/")["method"], "GET")

    def test_encoded_directory_is_not_decoded(self):
        self.assertEqual(run("/caf%C3%A9/")["uri"], "/caf%C3%A9/index.html")

    def test_input_event_not_mutated(self):
        event = make_event("/docs/")
        handler(event)
        self.assertEqual(event["request"]["uri"], "/docs/")


class FilePassThroughTests(unittest.TestCase):
    def test_css_unchanged(self):
        self.assertEqual(run("/a.css")["uri"], "/a.css")

    def test_nested_hashed_asset_unchanged(self):
        self.assertEqual(run("/assets/app.3f9a1c2e.js")["uri"], "/assets/app.3f9a1c2e.js")

    def test_explicit_index_unchanged(self):
        self.assertEqual(run("/docs/index.html")["uri"], "/docs/index.html")

    def test_file_with_query_unchanged(self):
        result = run("/a.css", "v=3")
        self.assertEqual(result["uri"], "/a.css")
        self.assertEqual(result["querystring"], {"v": {"value": "3"}})

    def test_dotfile_segment_is_a_file(self):
        self.assertEqual(run("/.well-known/security.txt")["uri"], "/.well-known/security.txt")

    def test_dot_in_directory_does_not_count(self):
        # Only the LAST segment decides: /v1.2/guide has no extension.
        self.assertEqual(run("/v1.2/guide")["statusCode"], 301)

    def test_encoded_file_name_with_literal_dot(self):
        self.assertEqual(run("/files/caf%C3%A9.pdf")["uri"], "/files/caf%C3%A9.pdf")


class RedirectTests(unittest.TestCase):
    def location(self, uri, query=""):
        result = run(uri, query)
        self.assertEqual(result["statusCode"], 301)
        self.assertEqual(result["statusDescription"], "Moved Permanently")
        return result["headers"]["location"]["value"]

    def test_no_trailing_slash_redirects(self):
        self.assertEqual(self.location("/docs"), "/docs/")

    def test_nested_redirect(self):
        self.assertEqual(self.location("/docs/guides"), "/docs/guides/")

    def test_redirect_keeps_query(self):
        self.assertEqual(self.location("/docs", "page=2&lang=en"), "/docs/?page=2&lang=en")

    def test_redirect_keeps_bare_key(self):
        self.assertEqual(self.location("/docs", "preview"), "/docs/?preview")

    def test_redirect_keeps_repeated_keys(self):
        # CloudFront groups repeated keys into multiValue, so they come out
        # adjacent: same meaning, possibly a different order.
        self.assertEqual(self.location("/docs", "tag=a&x=1&tag=b"), "/docs/?tag=a&tag=b&x=1")

    def test_redirect_keeps_encoded_query_values(self):
        self.assertEqual(self.location("/search", "q=a%20b%26c"), "/search/?q=a%20b%26c")

    def test_encoded_path_redirect_stays_encoded(self):
        self.assertEqual(self.location("/caf%C3%A9"), "/caf%C3%A9/")

    def test_encoded_slash_is_not_a_slash(self):
        self.assertEqual(self.location("/docs%2F"), "/docs%2F/")

    def test_encoded_dot_is_not_a_dot(self):
        self.assertEqual(self.location("/a%2Ecss"), "/a%2Ecss/")

    def test_redirect_is_cacheable(self):
        self.assertEqual(run("/docs")["headers"]["cache-control"]["value"], "public, max-age=3600")


class QueryStringTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(build_query_string({}), "")

    def test_multivalue(self):
        qs = {"a": {"value": "1", "multiValue": [{"value": "1"}, {"value": "2"}]}}
        self.assertEqual(build_query_string(qs), "?a=1&a=2")

    def test_make_event_does_not_decode(self):
        event = make_event("/x", "q=a+b%2B")
        self.assertEqual(event["request"]["querystring"], {"q": {"value": "a+b%2B"}})

    def test_make_event_ignores_empty_pairs(self):
        self.assertEqual(make_event("/x", "a=1&&b=")["request"]["querystring"],
                         {"a": {"value": "1"}, "b": {"value": ""}})


class DecideTests(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(decide("/")["action"], "rewrite")
        self.assertEqual(decide("/a.css")["action"], "pass")
        self.assertEqual(decide("/docs?x=1"), {"input": "/docs?x=1", "action": "redirect",
                                              "status": 301, "location": "/docs/?x=1"})


if __name__ == "__main__":
    unittest.main()
