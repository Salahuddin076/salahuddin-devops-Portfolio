#!/usr/bin/env python3
"""Run stdlib unittest discovery and write a JUnit XML report.

CodeBuild report groups read JUnit XML. pytest is not used in this project,
so this small runner keeps the build stdlib-only: the same tests as
`python3 -m unittest discover -s tests`, plus a report file.

Usage:
  junit_runner.py --start-dir tests --output reports/junit/unit.xml
Exit code is 0 only when every test passed (skips are allowed).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import unittest
import xml.etree.ElementTree as ET


class RecordingResult(unittest.TextTestResult):
    """TextTestResult that also records per-test outcome and duration."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.records: list[dict] = []
        self._started: dict[str, float] = {}

    def startTest(self, test) -> None:  # noqa: N802 (unittest API)
        self._started[test.id()] = time.perf_counter()
        super().startTest(test)

    def _record(self, test, outcome: str, detail: str = "", message: str = "") -> None:
        started = self._started.pop(test.id(), time.perf_counter())
        test_id = test.id()
        classname, _, name = test_id.rpartition(".")
        self.records.append(
            {
                "classname": classname or test_id,
                "name": name or test_id,
                "time": time.perf_counter() - started,
                "outcome": outcome,
                "message": message,
                "detail": detail,
            }
        )

    def addSuccess(self, test) -> None:  # noqa: N802
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err) -> None:  # noqa: N802
        super().addFailure(test, err)
        self._record(test, "failure", "".join(traceback.format_exception(*err)), str(err[1]))

    def addError(self, test, err) -> None:  # noqa: N802
        super().addError(test, err)
        self._record(test, "error", "".join(traceback.format_exception(*err)), str(err[1]))

    def addSkip(self, test, reason) -> None:  # noqa: N802
        super().addSkip(test, reason)
        self._record(test, "skipped", message=reason)

    def addExpectedFailure(self, test, err) -> None:  # noqa: N802
        super().addExpectedFailure(test, err)
        self._record(test, "passed")

    def addUnexpectedSuccess(self, test) -> None:  # noqa: N802
        super().addUnexpectedSuccess(test)
        self._record(test, "failure", message="unexpected success")


def to_junit_xml(records: list[dict], suite_name: str) -> ET.ElementTree:
    counts = {k: sum(1 for r in records if r["outcome"] == k) for k in ("failure", "error", "skipped")}
    suites = ET.Element("testsuites")
    suite = ET.SubElement(
        suites,
        "testsuite",
        name=suite_name,
        tests=str(len(records)),
        failures=str(counts["failure"]),
        errors=str(counts["error"]),
        skipped=str(counts["skipped"]),
        time=f"{sum(r['time'] for r in records):.3f}",
    )
    for record in records:
        case = ET.SubElement(
            suite, "testcase", classname=record["classname"], name=record["name"], time=f"{record['time']:.3f}"
        )
        if record["outcome"] in ("failure", "error"):
            child = ET.SubElement(case, record["outcome"], message=record["message"][:500])
            child.text = record["detail"]
        elif record["outcome"] == "skipped":
            ET.SubElement(case, "skipped", message=record["message"])
    ET.indent(suites)
    return ET.ElementTree(suites)


def run(start_dir: str, output: str, suite_name: str, top_level_dir: str | None = None, stream=None) -> int:
    suite = unittest.defaultTestLoader.discover(start_dir, top_level_dir=top_level_dir)
    runner = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2, resultclass=RecordingResult)
    result = runner.run(suite)
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    to_junit_xml(result.records, suite_name).write(output, encoding="utf-8", xml_declaration=True)
    print(f"junit report: {output} ({len(result.records)} tests)", file=stream or sys.stderr)
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="unittest discovery with a JUnit XML report")
    parser.add_argument("--start-dir", default="tests")
    parser.add_argument("--top-level-dir", default=None)
    parser.add_argument("--output", default="reports/junit/unit.xml")
    parser.add_argument("--suite-name", default="unit")
    args = parser.parse_args(argv)
    return run(args.start_dir, args.output, args.suite_name, args.top_level_dir)


if __name__ == "__main__":
    sys.exit(main())
