import datetime as dt
import unittest

import helpers
import trivyignore_check as tc

TODAY = dt.date(2026, 10, 14)


def check(name, today=TODAY, max_days=180):
    text = (helpers.TRIVYIGNORE_FIXTURES / name).read_text(encoding="utf-8")
    return tc.check_text(text, name, today, max_days)


class TrivyignoreTests(unittest.TestCase):
    def test_good_file(self):
        entries, problems = check("good.trivyignore")
        self.assertEqual(problems, [])
        self.assertEqual([e.finding_id for e in entries], ["CVE-2026-0001", "CVE-2026-0002", "GHSA-aaaa-bbbb-cccc"])
        self.assertEqual(entries[1].expires, dt.date(2027, 1, 15))  # date inside the comment
        self.assertEqual(entries[0].reason, "not reachable; owner: team-a")

    def test_bad_file_rules(self):
        _, problems = check("bad.trivyignore")
        got = sorted((p.line, p.rule) for p in problems)
        self.assertEqual(got, [
            (1, "TI001"), (1, "TI002"),  # no expiry, no reason
            (2, "TI002"),                # no reason
            (3, "TI003"),                # expired
            (4, "TI004"),                # too far out
            (5, "TI001"),                # invalid date
            (7, "TI005"),                # duplicate
        ])

    def test_entry_expires_at_end_of_its_day(self):
        text = "CVE-1 exp:2026-10-14 # reason: last day\n"
        self.assertEqual(tc.check_text(text, "x", TODAY)[1], [])
        self.assertEqual([p.rule for p in tc.check_text(text, "x", TODAY + dt.timedelta(days=1))[1]], ["TI003"])

    def test_good_file_goes_bad_with_time(self):
        _, problems = check("good.trivyignore", today=dt.date(2027, 6, 1))
        self.assertEqual({p.rule for p in problems}, {"TI003"})

    def test_shipped_trivyignore_is_valid_today(self):
        text = (helpers.PROJECT / ".trivyignore").read_text(encoding="utf-8")
        entries, problems = tc.check_text(text, ".trivyignore", dt.date.today())
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
