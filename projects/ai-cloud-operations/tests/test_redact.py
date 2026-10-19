from __future__ import annotations

import unittest

from aiops.redact import redact


class RedactTests(unittest.TestCase):
    def test_email_is_redacted(self):
        self.assertEqual(redact("contact alice@example.com for help"),
                          "contact [REDACTED_EMAIL] for help")

    def test_ipv4_is_redacted(self):
        self.assertEqual(redact("client 203.0.113.42 timed out"),
                          "client [REDACTED_IP] timed out")

    def test_keyvalue_token_is_redacted(self):
        out = redact("auth failed: token=abcdef123456 rejected")
        self.assertIn("[REDACTED_SECRET]", out)
        self.assertNotIn("abcdef123456", out)

    def test_keyvalue_api_key_quoted_is_redacted(self):
        out = redact('config: api_key="sk-live-1234567890abcd" loaded')
        self.assertNotIn("1234567890abcd", out)

    def test_bare_provider_shaped_secret_is_redacted(self):
        out = redact("using token ghp_1234567890abcdef for push")
        self.assertIn("[REDACTED_SECRET]", out)
        self.assertNotIn("ghp_1234567890abcdef", out)

    def test_plain_text_is_untouched(self):
        text = "request completed in 42ms"
        self.assertEqual(redact(text), text)

    def test_multiple_patterns_in_one_line(self):
        out = redact("user alice@example.com from 203.0.113.42 used token=deadbeefcafe00")
        self.assertNotIn("alice@example.com", out)
        self.assertNotIn("203.0.113.42", out)
        self.assertNotIn("deadbeefcafe00", out)


if __name__ == "__main__":
    unittest.main()
