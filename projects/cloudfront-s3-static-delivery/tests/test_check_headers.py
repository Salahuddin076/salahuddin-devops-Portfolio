"""Security header checks on captured responses (scripts/check_headers.py). No network."""

import unittest

from helpers import HEADERS_BAD, HEADERS_GOOD
from check_headers import HeaderError, check, parse_headers

BASE = {
    "strict-transport-security": ["max-age=31536000; includeSubDomains"],
    "content-security-policy": ["default-src 'self'; frame-ancestors 'none'"],
    "x-content-type-options": ["nosniff"],
    "x-frame-options": ["DENY"],
    "referrer-policy": ["no-referrer"],
}


def levels(headers, name):
    return [f.level for f in check(headers) if f.header == name]


def with_(**changes):
    h = dict(BASE)
    for k, v in changes.items():
        key = k.replace("_", "-")
        if v is None:
            h.pop(key, None)
        else:
            h[key] = [v]
    return h


class SampleFileTests(unittest.TestCase):
    def test_good_file_passes(self):
        status, headers = parse_headers(HEADERS_GOOD.read_text())
        self.assertEqual(status, "HTTP/2 200")  # last response of the redirect chain
        findings = check(headers)
        self.assertEqual({f.level for f in findings}, {"PASS"})
        self.assertEqual(len(findings), 5)

    def test_bad_file_fails_every_check(self):
        _, headers = parse_headers(HEADERS_BAD.read_text())
        fails = {f.header for f in check(headers) if f.level == "FAIL"}
        self.assertEqual(fails, {"Strict-Transport-Security", "Content-Security-Policy",
                                 "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"})


class HstsTests(unittest.TestCase):
    def test_exactly_one_year_passes(self):
        self.assertEqual(levels(BASE, "Strict-Transport-Security"), ["PASS"])

    def test_below_one_year_fails(self):
        h = with_(strict_transport_security="max-age=31535999; includeSubDomains")
        self.assertEqual(levels(h, "Strict-Transport-Security"), ["FAIL"])

    def test_missing_max_age_fails(self):
        self.assertEqual(levels(with_(strict_transport_security="includeSubDomains"),
                                "Strict-Transport-Security"), ["FAIL"])

    def test_quoted_and_case_insensitive(self):
        h = with_(strict_transport_security='MAX-AGE="63072000"; includesubdomains')
        self.assertEqual(levels(h, "Strict-Transport-Security"), ["PASS"])

    def test_no_include_subdomains_warns(self):
        self.assertEqual(levels(with_(strict_transport_security="max-age=63072000"),
                                "Strict-Transport-Security"), ["PASS", "WARN"])

    def test_missing_fails(self):
        self.assertEqual(levels(with_(strict_transport_security=None), "Strict-Transport-Security"), ["FAIL"])


class OtherHeaderTests(unittest.TestCase):
    def test_csp_unsafe_inline_warns(self):
        h = with_(content_security_policy="default-src 'self'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.assertEqual(levels(h, "Content-Security-Policy"), ["PASS", "WARN"])

    def test_csp_default_src_unsafe_eval_warns_without_script_src(self):
        h = with_(content_security_policy="default-src 'self' 'unsafe-eval'; frame-ancestors 'none'")
        self.assertIn("WARN", levels(h, "Content-Security-Policy"))

    def test_csp_without_frame_ancestors_warns(self):
        self.assertEqual(levels(with_(content_security_policy="default-src 'self'"),
                                "Content-Security-Policy"), ["PASS", "WARN"])

    def test_empty_csp_fails(self):
        self.assertEqual(levels(with_(content_security_policy=" "), "Content-Security-Policy"), ["FAIL"])

    def test_nosniff_exact(self):
        self.assertEqual(levels(with_(x_content_type_options="sniff"), "X-Content-Type-Options"), ["FAIL"])

    def test_frame_options(self):
        self.assertEqual(levels(with_(x_frame_options="sameorigin"), "X-Frame-Options"), ["PASS"])
        self.assertEqual(levels(with_(x_frame_options="ALLOW-FROM https://example.com"), "X-Frame-Options"), ["FAIL"])

    def test_referrer_policies(self):
        for ok in ("no-referrer", "same-origin", "strict-origin", "strict-origin-when-cross-origin"):
            self.assertEqual(levels(with_(referrer_policy=ok), "Referrer-Policy"), ["PASS"])
        for bad in ("unsafe-url", "no-referrer-when-downgrade", "origin"):
            self.assertEqual(levels(with_(referrer_policy=bad), "Referrer-Policy"), ["FAIL"])


class ParseTests(unittest.TestCase):
    def test_bare_headers_without_status(self):
        status, headers = parse_headers("X-Frame-Options: DENY\r\nReferrer-Policy: no-referrer\r\n")
        self.assertIsNone(status)
        self.assertEqual(headers["x-frame-options"], ["DENY"])

    def test_names_lowercased_and_values_trimmed(self):
        _, headers = parse_headers("HTTP/1.1 200 OK\nStrict-Transport-Security:   max-age=1  \n")
        self.assertEqual(headers["strict-transport-security"], ["max-age=1"])

    def test_empty_input(self):
        with self.assertRaises(HeaderError):
            parse_headers("\n\n")

    def test_garbage_line(self):
        with self.assertRaises(HeaderError):
            parse_headers("HTTP/2 200\nthis is not a header\n")

    def test_status_only(self):
        with self.assertRaises(HeaderError):
            parse_headers("HTTP/2 200\n")


if __name__ == "__main__":
    unittest.main()
