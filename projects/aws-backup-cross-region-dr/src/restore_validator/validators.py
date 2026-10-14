"""One validation per restored resource type.

Each validator answers "is this restored copy usable?" with the cheapest
check that would catch a broken restore, and returns every check it ran so
the message posted to AWS Backup explains the verdict:

* RDS: the instance is ``available``, its endpoint accepts TCP connections,
  and (when a query runner is configured) a row-count query returns at
  least the expected number of rows.
* DynamoDB: the table holds at least ``dynamodb_min_items`` items.
* S3: the bucket holds at least ``s3_min_objects`` objects, and a sample of
  objects matches the checksum S3 stored for it.
* EBS: the restored volume is ``available``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from adapters import ResourceNotFound, ResourcePort, resource_id

SUCCESSFUL = "SUCCESSFUL"
FAILED = "FAILED"


@dataclass(frozen=True)
class ValidationConfig:
    restore_test_tag_key: str = "awsbackup-restore-test"
    rds_connect_timeout_seconds: float = 5.0
    rds_row_count_query: str = ""
    rds_min_rows: int = 1
    dynamodb_min_items: int = 1
    s3_min_objects: int = 1
    s3_checksum_sample: int = 5
    early_cleanup: bool = False
    metric_namespace: str = "BackupDR/RestoreTesting"


@dataclass
class Outcome:
    status: str
    checks: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "; ".join(self.checks)


def _result(checks: list[tuple[bool, str]]) -> Outcome:
    ok = all(passed for passed, _ in checks)
    return Outcome(SUCCESSFUL if ok else FAILED, [("ok: " if p else "FAIL: ") + text for p, text in checks])


def validate_rds(arn: str, port: ResourcePort, cfg: ValidationConfig) -> Outcome:
    identifier = resource_id("RDS", arn)
    instance = port.rds_instance(identifier)
    checks = [(instance["status"] == "available", f"instance {identifier} status {instance['status']}")]
    host, db_port = instance.get("host"), instance.get("port")
    if not host or not db_port:
        checks.append((False, "instance has no endpoint"))
        return _result(checks)
    reachable = port.tcp_reachable(host, int(db_port), cfg.rds_connect_timeout_seconds)
    checks.append((reachable, f"endpoint {host}:{db_port} {'reachable' if reachable else 'unreachable'}"))
    if reachable and cfg.rds_row_count_query:
        rows = port.rds_row_count(host, int(db_port), cfg.rds_row_count_query)
        if rows is None:
            checks.append((True, "row count skipped (no query runner configured)"))
        else:
            checks.append((rows >= cfg.rds_min_rows, f"row count {rows} (minimum {cfg.rds_min_rows})"))
    return _result(checks)


def validate_dynamodb(arn: str, port: ResourcePort, cfg: ValidationConfig) -> Outcome:
    table = resource_id("DynamoDB", arn)
    count = port.dynamodb_count_items(table, stop_at=cfg.dynamodb_min_items)
    return _result([(count >= cfg.dynamodb_min_items, f"table {table} has >= {count} items (minimum {cfg.dynamodb_min_items})")])


def validate_s3(arn: str, port: ResourcePort, cfg: ValidationConfig) -> Outcome:
    bucket = resource_id("S3", arn)
    count = port.s3_count_objects(bucket, stop_at=cfg.s3_min_objects)
    checks = [(count >= cfg.s3_min_objects, f"bucket {bucket} has >= {count} objects (minimum {cfg.s3_min_objects})")]
    if cfg.s3_checksum_sample > 0 and count > 0:
        sample = port.s3_checksum_sample(bucket, cfg.s3_checksum_sample)
        verifiable = [s for s in sample if s.get("algorithm")]
        mismatched = [s["key"] for s in verifiable if s["stored"] != s["computed"]]
        if mismatched:
            checks.append((False, f"checksum mismatch on {len(mismatched)}/{len(verifiable)} sampled objects: {', '.join(mismatched[:3])}"))
        elif verifiable:
            checks.append((True, f"checksums match on {len(verifiable)}/{len(sample)} sampled objects"))
        else:
            checks.append((True, f"no verifiable checksum in {len(sample)} sampled objects (multipart or SSE-KMS without additional checksums)"))
    return _result(checks)


def validate_ebs(arn: str, port: ResourcePort, cfg: ValidationConfig) -> Outcome:
    volume_id = resource_id("EBS", arn)
    state = port.ebs_volume(volume_id)["state"]
    return _result([(state == "available", f"volume {volume_id} state {state}")])


VALIDATORS: dict[str, Callable[[str, ResourcePort, ValidationConfig], Outcome]] = {
    "RDS": validate_rds,
    "DynamoDB": validate_dynamodb,
    "S3": validate_s3,
    "EBS": validate_ebs,
}


def validate(resource_type: str, arn: str, port: ResourcePort, cfg: ValidationConfig) -> Outcome:
    """Run the validator for ``resource_type``. Errors become a FAILED outcome."""
    validator = VALIDATORS[resource_type]
    try:
        return validator(arn, port, cfg)
    except ResourceNotFound as exc:
        return Outcome(FAILED, [f"FAIL: restored resource not found: {exc}"])
    except Exception as exc:  # any probe error means the restore is not proven usable
        return Outcome(FAILED, [f"FAIL: validation error {type(exc).__name__}: {exc}"])
