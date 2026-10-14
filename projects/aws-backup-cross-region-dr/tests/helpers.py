"""Shared test helpers: import paths, fixed clock, event and fake builders.

``src/restore_validator`` goes on the import path the same way the Lambda
runtime sees it (handler modules at the zip root).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT / "src" / "restore_validator"
SCRIPTS_DIR = PROJECT / "scripts"
POLICY_FILE = PROJECT / "policy" / "backup-policy.json"
BAD_POLICY_FILE = PROJECT / "policy" / "fixtures" / "backup-policy-noncompliant.json"
SAMPLE_JOBS = PROJECT / "sample-data" / "jobs.json"

for p in (SRC_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from adapters import FakeBackup, FakeResources  # noqa: E402
from handler import Deps  # noqa: E402
from telemetry import Telemetry  # noqa: E402
from validators import ValidationConfig  # noqa: E402

START = 1_791_957_600.0  # 2026-10-14T06:00:00Z
TAG = "awsbackup-restore-test"
PLAN_ARN = "arn:aws:backup:us-west-2:123456789012:restore-testing-plan:backup_dr_demo_restore_tests-0a1b2c3d"

ARNS = {
    "RDS": "arn:aws:rds:us-west-2:123456789012:db:awsbackup-restore-test-orders-db",
    "DynamoDB": "arn:aws:dynamodb:us-west-2:123456789012:table/awsbackup-restore-test-sessions",
    "S3": "arn:aws:s3:::awsbackup-restore-test-media-assets-0001",
    "EBS": "arn:aws:ec2:us-west-2:123456789012:volume/vol-0example0000restore",
}


class FakeClock:
    def __init__(self, start: float = START) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def healthy_resource(resource_type: str, tagged: bool = True) -> dict[str, Any]:
    tags = {TAG: "true"} if tagged else {"backup-policy": "gold"}
    if resource_type == "RDS":
        return {"type": "RDS", "state": "available", "host": "restored.example.internal", "port": 5432, "tags": tags}
    if resource_type == "DynamoDB":
        return {"type": "DynamoDB", "items": 1200, "tags": tags}
    if resource_type == "S3":
        objects = [{"key": f"img/{i}.png", "algorithm": "SHA256", "stored": f"c{i}=", "computed": f"c{i}="} for i in range(8)]
        return {"type": "S3", "objects": objects, "tags": tags}
    if resource_type == "EBS":
        return {"type": "EBS", "state": "available", "tags": tags}
    raise ValueError(resource_type)


def restore_job(job_id: str, resource_type: str, *, test: bool = True, arn: str | None = None) -> dict[str, Any]:
    job = {
        "RestoreJobId": job_id,
        "ResourceType": resource_type,
        "Status": "COMPLETED",
        "CreatedResourceArn": arn or ARNS.get(resource_type, f"arn:aws:example:::{resource_type}"),
    }
    if test:
        job["CreatedBy"] = {"RestoreTestingPlanArn": PLAN_ARN}
    return job


def restore_event(job_id: str, status: str = "COMPLETED") -> dict[str, Any]:
    """EventBridge 'Restore Job State Change' envelope (fields used by the handler)."""
    return {
        "version": "0",
        "id": f"evt-{job_id}",
        "detail-type": "Restore Job State Change",
        "source": "aws.backup",
        "account": "123456789012",
        "region": "us-west-2",
        "detail": {"restoreJobId": job_id, "status": status},
    }


class Harness:
    def __init__(self, resource_type: str | None = None, *, tagged: bool = True, **config: Any) -> None:
        self.clock = FakeClock()
        self.stream = io.StringIO()
        self.backup = FakeBackup()
        self.resources = FakeResources()
        if resource_type:
            self.add(resource_type, tagged=tagged)
        self.deps = Deps(
            backup=self.backup,
            resources=self.resources,
            telemetry=Telemetry("restore-validator", stream=self.stream, clock=self.clock),
            config=ValidationConfig(**config),
            clock=self.clock,
        )

    def add(self, resource_type: str, job_id: str = "rj-1", *, tagged: bool = True, test: bool = True) -> dict[str, Any]:
        res = healthy_resource(resource_type, tagged)
        self.resources.resources[ARNS[resource_type]] = res
        self.backup.jobs[job_id] = restore_job(job_id, resource_type, test=test)
        return res

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line]

    def emf(self) -> list[dict[str, Any]]:
        return [line for line in self.lines() if "_aws" in line]
