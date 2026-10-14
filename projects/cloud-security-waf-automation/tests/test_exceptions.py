"""Exceptions: valid, expired, wrong resource, wrong rule, malformed files."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from helpers import change, plan

import check_plan

TODAY = dt.date(2026, 10, 14)
SG_PLAN = plan(change("aws_security_group.bastion", {"ingress": [
    {"from_port": 22, "to_port": 22, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"], "ipv6_cidr_blocks": []}]}))


def exc(**over):
    e = {"rule_id": "CSP-SG-001", "resource": "aws_security_group.bastion", "owner": "platform-team@example.com",
         "reason": "vendor appliance, replacement tracked", "expires": "2026-12-31"}
    e.update(over)
    return e


class ExceptionFileMixin:
    def write(self, data) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.write(data if isinstance(data, str) else json.dumps(data))
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def evaluate(self, *entries, today=TODAY):
        exceptions = check_plan.load_exceptions(self.write({"exceptions": list(entries)}))
        return check_plan.evaluate(SG_PLAN, "plan.json", exceptions, today)


class ExceptionTests(ExceptionFileMixin, unittest.TestCase):
    def test_valid_exception_suppresses_and_passes(self):
        r = self.evaluate(exc())
        self.assertEqual(r.active, [])
        self.assertEqual(len(r.excepted), 1)
        self.assertEqual(r.excepted[0].excepted_by["owner"], "platform-team@example.com")
        self.assertFalse(r.failed)

    def test_exception_valid_through_its_expiry_date(self):
        self.assertFalse(self.evaluate(exc(expires="2026-10-14")).failed)

    def test_expired_exception_is_ignored_and_reported(self):
        r = self.evaluate(exc(expires="2026-10-13"))
        self.assertTrue(r.failed)
        self.assertEqual(len(r.active), 1)
        self.assertEqual([e["resource"] for e in r.expired_exceptions], ["aws_security_group.bastion"])
        self.assertIn("EXPIRED", check_plan.render_text(r))

    def test_wrong_resource_does_not_match(self):
        r = self.evaluate(exc(resource="aws_security_group.other"))
        self.assertTrue(r.failed)
        self.assertEqual(len(r.unused_exceptions), 1)

    def test_wrong_rule_does_not_match(self):
        r = self.evaluate(exc(rule_id="CSP-RDS-001"))
        self.assertTrue(r.failed)

    def test_today_injection_changes_the_outcome(self):
        self.assertFalse(self.evaluate(exc(), today=dt.date(2026, 12, 31)).failed)
        self.assertTrue(self.evaluate(exc(), today=dt.date(2027, 1, 1)).failed)


class MalformedExceptionFileTests(ExceptionFileMixin, unittest.TestCase):
    def assertRejected(self, data, fragment):
        with self.assertRaises(check_plan.InputError) as ctx:
            check_plan.load_exceptions(self.write(data))
        self.assertIn(fragment, str(ctx.exception))

    def test_missing_fields(self):
        for field in ("rule_id", "resource", "owner", "reason", "expires"):
            with self.subTest(field=field):
                entry = exc()
                del entry[field]
                self.assertRejected({"exceptions": [entry]}, field)

    def test_blank_owner(self):
        self.assertRejected({"exceptions": [exc(owner="  ")]}, "owner")

    def test_bad_date(self):
        self.assertRejected({"exceptions": [exc(expires="31/12/2026")]}, "YYYY-MM-DD")

    def test_unknown_rule(self):
        self.assertRejected({"exceptions": [exc(rule_id="CSP-XXX-999")]}, "unknown rule")

    def test_not_a_list(self):
        self.assertRejected({"exceptions": {}}, "'exceptions' list")

    def test_invalid_json(self):
        self.assertRejected("{", "not valid JSON")

    def test_shipped_exceptions_file_is_valid(self):
        entries = check_plan.load_exceptions(check_plan.default_exceptions_path())
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
