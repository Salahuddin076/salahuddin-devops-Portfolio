from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aiops.io import (
    InputError,
    format_timestamp,
    parse_timestamp,
    read_alerts,
    read_deploys,
    read_logs,
    write_alerts,
    write_deploys,
    write_logs,
)
from aiops.models import Alert, DeployEvent, LogEvent


class TimestampTests(unittest.TestCase):
    def test_parse_z_suffix(self):
        dt = parse_timestamp("2026-01-01T00:00:00Z")
        self.assertEqual(dt, datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_parse_rejects_naive(self):
        with self.assertRaises(ValueError):
            parse_timestamp("2026-01-01T00:00:00")

    def test_round_trip(self):
        dt = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
        self.assertEqual(parse_timestamp(format_timestamp(dt)), dt)


class ReadWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_logs_round_trip(self):
        events = [LogEvent(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), service="a",
                            level="ERROR", message="boom")]
        path = self.dir / "logs.jsonl"
        write_logs(path, events)
        self.assertEqual(read_logs(path), events)

    def test_deploys_round_trip(self):
        events = [DeployEvent(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), service="a",
                               version="v1", actor="bob")]
        path = self.dir / "deploys.jsonl"
        write_deploys(path, events)
        self.assertEqual(read_deploys(path), events)

    def test_alerts_round_trip(self):
        events = [Alert(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), service="a",
                         name="HighErrorRate", severity="critical")]
        path = self.dir / "alerts.jsonl"
        write_alerts(path, events)
        self.assertEqual(read_alerts(path), events)

    def test_missing_file_raises_input_error(self):
        with self.assertRaises(InputError):
            read_logs(self.dir / "nope.jsonl")

    def test_malformed_json_raises_with_line_number(self):
        path = self.dir / "bad.jsonl"
        path.write_text('{"timestamp": "2026-01-01T00:00:00Z", "service": "a"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(InputError) as ctx:
            read_logs(path)
        self.assertIn(":2:", str(ctx.exception))

    def test_missing_required_field_raises(self):
        path = self.dir / "bad.jsonl"
        path.write_text('{"timestamp": "2026-01-01T00:00:00Z"}\n', encoding="utf-8")
        with self.assertRaises(InputError):
            read_logs(path)

    def test_blank_lines_are_skipped(self):
        path = self.dir / "logs.jsonl"
        path.write_text('\n{"timestamp": "2026-01-01T00:00:00Z", "service": "a", "level": "INFO", '
                         '"message": "x"}\n\n', encoding="utf-8")
        self.assertEqual(len(read_logs(path)), 1)


if __name__ == "__main__":
    unittest.main()
