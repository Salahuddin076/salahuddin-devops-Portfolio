"""Restore-testing validator: EventBridge ``Restore Job State Change`` -> verdict.

Triggered in the DR region by an EventBridge rule on ``source = aws.backup``,
``detail-type = Restore Job State Change``, ``detail.status = COMPLETED``.

Per event:

1. Look the job up with ``DescribeRestoreJob``. Only jobs started by a
   restore testing plan (``CreatedBy.RestoreTestingPlanArn``) are validated;
   an operator's manual restore is logged and left alone.
2. Run the validator for the resource type (RDS, DynamoDB, S3, EBS) against
   the restored resource (``CreatedResourceArn``).
3. Report ``SUCCESSFUL`` or ``FAILED`` with ``PutRestoreValidationResult``,
   which AWS Backup records on the restore job and shows in its console.
4. Emit one structured log line and one EMF line for the custom metric
   ``RestoreValidationSucceeded`` (1 or 0, dimension ``ResourceType``).

Restored resources are not this function's responsibility to remove: AWS
Backup restore testing deletes them when the plan's validation window ends.
``cleanup`` exists for one case only, early deletion when
``EARLY_CLEANUP=true``, and refuses any resource that does not carry the
restore-testing tag, so a misrouted event can never delete a real resource.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from adapters import BackupPort, ResourceNotFound, ResourcePort
from telemetry import Telemetry
from validators import FAILED, SUCCESSFUL, VALIDATORS, ValidationConfig, validate

SERVICE = "restore-validator"
# AWS Backup stores the message on the job; keep it short and bounded.
MAX_MESSAGE_LENGTH = 1000
CLEANUP_SUPPORTED = ("RDS", "DynamoDB", "EBS")


@dataclass
class Deps:
    backup: BackupPort
    resources: ResourcePort
    telemetry: Telemetry
    config: ValidationConfig
    clock: Callable[[], float] = time.time


@dataclass
class CleanupResult:
    action: str  # deleted | refused | unsupported | not_found
    reason: str


def _env_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def config_from_env(env: Mapping[str, str]) -> ValidationConfig:
    defaults = ValidationConfig()
    return ValidationConfig(
        restore_test_tag_key=env.get("RESTORE_TEST_TAG_KEY", defaults.restore_test_tag_key),
        rds_connect_timeout_seconds=float(env.get("RDS_CONNECT_TIMEOUT_SECONDS", defaults.rds_connect_timeout_seconds)),
        rds_row_count_query=env.get("RDS_ROW_COUNT_QUERY", defaults.rds_row_count_query),
        rds_min_rows=int(env.get("RDS_MIN_ROWS", defaults.rds_min_rows)),
        dynamodb_min_items=int(env.get("DYNAMODB_MIN_ITEMS", defaults.dynamodb_min_items)),
        s3_min_objects=int(env.get("S3_MIN_OBJECTS", defaults.s3_min_objects)),
        s3_checksum_sample=int(env.get("S3_CHECKSUM_SAMPLE", defaults.s3_checksum_sample)),
        early_cleanup=_env_bool(env.get("EARLY_CLEANUP")),
        metric_namespace=env.get("METRIC_NAMESPACE", defaults.metric_namespace),
    )


def cleanup(resource_type: str, resource_arn: str, deps: Deps) -> CleanupResult:
    """Delete a restored test resource early, but only if it is tagged as one.

    The tag check is the safety interlock: the Lambda role's delete
    permissions carry the same ``aws:ResourceTag`` condition, so both the
    code and IAM refuse an untagged (that is, real) resource.
    """
    if resource_type not in CLEANUP_SUPPORTED:
        return CleanupResult("unsupported", f"{resource_type} is left to restore testing's own deletion")
    try:
        tags = deps.resources.tags(resource_type, resource_arn)
    except ResourceNotFound:
        return CleanupResult("not_found", "resource already gone")
    tag_key = deps.config.restore_test_tag_key
    if tag_key not in tags:
        return CleanupResult("refused", f"resource lacks the {tag_key!r} tag; refusing to delete")
    deps.resources.delete(resource_type, resource_arn)
    return CleanupResult("deleted", f"deleted early ({tag_key}={tags[tag_key]})")


def handle(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    tel = deps.telemetry
    detail = event.get("detail") or {}
    job_id = detail.get("restoreJobId")
    if not job_id:
        tel.log("WARNING", "event has no restoreJobId; ignored", event_id=event.get("id"))
        return {"status": "ignored", "reason": "no restoreJobId"}
    if detail.get("status") != "COMPLETED":
        tel.log("INFO", "restore job not completed; ignored", restore_job_id=job_id, job_status=detail.get("status"))
        return {"status": "ignored", "reason": f"status {detail.get('status')}", "restoreJobId": job_id}

    job = deps.backup.describe_restore_job(job_id)
    plan_arn = (job.get("CreatedBy") or {}).get("RestoreTestingPlanArn")
    resource_type = job.get("ResourceType", "")
    created_arn = job.get("CreatedResourceArn", "")
    context = {"restore_job_id": job_id, "resource_type": resource_type, "created_resource_arn": created_arn}

    if not plan_arn:
        tel.log("INFO", "not a restore-testing job; ignored", **context)
        return {"status": "ignored", "reason": "not a restore-testing job", "restoreJobId": job_id}
    if resource_type not in VALIDATORS:
        # No verdict is posted: AWS Backup keeps the job's validation status
        # empty, which is honest, and the log says why.
        tel.log("WARNING", "no validator for resource type; skipped", restore_testing_plan_arn=plan_arn, **context)
        return {"status": "skipped", "reason": f"unsupported resource type {resource_type}", "restoreJobId": job_id}

    started = deps.clock()
    outcome = validate(resource_type, created_arn, deps.resources, deps.config)
    message = outcome.message[:MAX_MESSAGE_LENGTH]
    deps.backup.put_restore_validation_result(job_id, outcome.status, message)
    succeeded = outcome.status == SUCCESSFUL

    tel.log(
        "INFO" if succeeded else "ERROR",
        "restore validation " + ("succeeded" if succeeded else "failed"),
        validation_status=outcome.status,
        checks=outcome.checks,
        duration_ms=int((deps.clock() - started) * 1000),
        restore_testing_plan_arn=plan_arn,
        **context,
    )
    tel.metric(
        namespace=deps.config.metric_namespace,
        resource_type=resource_type,
        succeeded=succeeded,
        restoreJobId=job_id,
        createdResourceArn=created_arn,
    )

    result: dict[str, Any] = {"status": outcome.status, "restoreJobId": job_id, "message": message}
    if deps.config.early_cleanup:
        cleaned = cleanup(resource_type, created_arn, deps)
        tel.log("INFO" if cleaned.action != "refused" else "WARNING", "early cleanup", action=cleaned.action, reason=cleaned.reason, **context)
        result["cleanup"] = cleaned.action
    return result


def _default_deps() -> Deps:  # pragma: no cover - only runs inside Lambda
    from adapters import Boto3Backup, Boto3Resources

    return Deps(
        backup=Boto3Backup(),
        resources=Boto3Resources(),
        telemetry=Telemetry(SERVICE, clock=time.time),
        config=config_from_env(os.environ),
    )


_DEPS: Deps | None = None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point. Dependencies are built once per execution environment."""
    global _DEPS
    if _DEPS is None:
        _DEPS = _default_deps()
    return handle(event, _DEPS)


__all__ = ["Deps", "CleanupResult", "cleanup", "config_from_env", "handle", "handler", "FAILED", "SUCCESSFUL"]
