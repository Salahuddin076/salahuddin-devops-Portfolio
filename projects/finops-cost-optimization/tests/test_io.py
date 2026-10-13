import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from helpers import D, rec

from finops.io import InputError, parse_tags, parse_timestamp, read_billing, write_billing

HEADER = "ChargePeriodStart,ChargePeriodEnd,ServiceName,BilledCost,EffectiveCost,Tags\n"


class IoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text: str) -> Path:
        path = self.dir / "billing.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_round_trip_preserves_values(self):
        original = [rec("12.345678", tags={"team": "a", "env": "prod"}), rec("0.5", committed=True)]
        path = self.dir / "rt.csv"
        write_billing(path, original)
        loaded = read_billing(path)
        self.assertEqual(loaded[0].effective_cost, D("12.345678"))
        self.assertEqual(loaded[0].tags, {"team": "a", "env": "prod"})
        self.assertEqual(loaded[1].billed_cost, D("0"))
        self.assertEqual(loaded[1].pricing_category, "Committed")

    def test_minimal_focus_columns_load_with_defaults(self):
        path = self._write(HEADER + '2026-09-01T00:00:00Z,2026-09-02T00:00:00Z,Amazon S3,1.00,1.00,\n')
        r = read_billing(path)[0]
        self.assertEqual((r.charge_category, r.pricing_category, r.tags), ("Usage", "On-Demand", {}))
        self.assertIsNone(r.list_cost)
        self.assertEqual(r.cost("list"), D("1.00"))

    def test_missing_required_column(self):
        path = self._write("ChargePeriodStart,ServiceName\n2026-09-01,Amazon S3\n")
        with self.assertRaisesRegex(InputError, "missing required column"):
            read_billing(path)

    def test_bad_tags_reports_line_number(self):
        path = self._write(HEADER + '2026-09-01T00:00:00Z,2026-09-02T00:00:00Z,Amazon S3,1,1,"{oops"\n')
        with self.assertRaisesRegex(InputError, r"billing\.csv:2"):
            read_billing(path)

    def test_end_before_start_rejected(self):
        path = self._write(HEADER + "2026-09-02T00:00:00Z,2026-09-01T00:00:00Z,Amazon S3,1,1,\n")
        with self.assertRaisesRegex(InputError, "after ChargePeriodStart"):
            read_billing(path)

    def test_timestamp_and_tag_parsing(self):
        self.assertEqual(parse_timestamp("2026-09-01T05:00:00+05:00"), datetime(2026, 9, 1, 0, 0))
        self.assertEqual(parse_timestamp("2026-09-01"), datetime(2026, 9, 1))
        self.assertEqual(parse_tags('{"team": null}'), {"team": ""})
        self.assertEqual(parse_tags("null"), {})
        with self.assertRaises(ValueError):
            parse_tags('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
