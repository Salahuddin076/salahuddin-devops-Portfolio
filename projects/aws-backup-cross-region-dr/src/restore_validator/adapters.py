"""Ports to AWS Backup and the restored resources, their boto3 adapters, and fakes.

The handler and the validators depend only on the two small interfaces below.
boto3 ships with the Lambda Python runtime, so the real adapters import it
lazily inside their constructors: the test suite never imports it and runs on
the standard library alone.

The fakes reproduce what the validators rely on, not the whole API: a restore
job record per job ID, per-resource state and tags, and a log of every
``PutRestoreValidationResult`` and delete call so tests can assert on side
effects.
"""

from __future__ import annotations

import base64
import hashlib
import socket
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# Objects larger than this are not downloaded for the checksum sample. A
# validation Lambda has a few hundred MB of memory and a 15-minute ceiling;
# the sample is a smoke test, not a full integrity scan.
MAX_CHECKSUM_OBJECT_BYTES = 8 * 1024 * 1024


class ResourceNotFound(Exception):
    """The restored resource does not exist (already deleted, or a bad ARN)."""


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


class BackupPort(Protocol):
    def describe_restore_job(self, restore_job_id: str) -> dict[str, Any]:
        """Return the DescribeRestoreJob response (PascalCase keys)."""

    def put_restore_validation_result(self, restore_job_id: str, status: str, message: str) -> None:
        """Report SUCCESSFUL or FAILED for a restore-testing job."""


class ResourcePort(Protocol):
    # RDS
    def rds_instance(self, identifier: str) -> dict[str, Any]:
        """Return {"status", "host", "port"}; raise ResourceNotFound."""

    def tcp_reachable(self, host: str, port: int, timeout: float) -> bool:
        """True when a TCP connection to host:port succeeds."""

    def rds_row_count(self, host: str, port: int, query: str) -> int | None:
        """Run a row-count query; None when no query runner is configured."""

    # DynamoDB
    def dynamodb_count_items(self, table: str, stop_at: int) -> int:
        """Count items, stopping early once ``stop_at`` is reached."""

    # S3
    def s3_count_objects(self, bucket: str, stop_at: int) -> int:
        """Count objects, stopping early once ``stop_at`` is reached."""

    def s3_checksum_sample(self, bucket: str, sample_size: int) -> list[dict[str, Any]]:
        """Return [{"key", "algorithm", "stored", "computed"}] for up to N objects."""

    # EBS
    def ebs_volume(self, volume_id: str) -> dict[str, Any]:
        """Return {"state"}; raise ResourceNotFound."""

    # Tags and cleanup
    def tags(self, resource_type: str, resource_arn: str) -> dict[str, str]:
        """Return the resource's tags as a plain dict."""

    def delete(self, resource_type: str, resource_arn: str) -> None:
        """Delete a restored resource (only called after the tag safety check)."""


# --------------------------------------------------------------------------
# ARN helpers shared by the adapters and the validators
# --------------------------------------------------------------------------


def resource_id(resource_type: str, arn: str) -> str:
    """Extract the identifier the service API expects from a resource ARN."""
    if resource_type == "S3":
        # arn:aws:s3:::bucket-name
        return arn.split(":::", 1)[1] if ":::" in arn else arn
    if resource_type == "RDS":
        # arn:aws:rds:region:account:db:identifier
        parts = arn.split(":")
        if len(parts) >= 7 and parts[5] == "db":
            return parts[6]
        raise ValueError(f"not an RDS DB instance ARN: {arn}")
    if resource_type in ("DynamoDB", "EBS"):
        # arn:aws:dynamodb:region:account:table/name, arn:aws:ec2:...:volume/vol-id
        tail = arn.split(":", 5)[-1]
        if "/" not in tail:
            raise ValueError(f"unexpected {resource_type} ARN: {arn}")
        return tail.split("/", 1)[1]
    raise ValueError(f"unsupported resource type {resource_type!r}")


# --------------------------------------------------------------------------
# boto3 adapters (used inside Lambda only)
# --------------------------------------------------------------------------


class Boto3Backup:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            import boto3  # available in the Lambda runtime

            client = boto3.client("backup")
        self._client = client

    def describe_restore_job(self, restore_job_id: str) -> dict[str, Any]:
        return self._client.describe_restore_job(RestoreJobId=restore_job_id)

    def put_restore_validation_result(self, restore_job_id: str, status: str, message: str) -> None:
        self._client.put_restore_validation_result(
            RestoreJobId=restore_job_id,
            ValidationStatus=status,
            ValidationStatusMessage=message,
        )


class Boto3Resources:
    """Real resource probes. ``row_counter`` is the database hook.

    The standard library has no PostgreSQL or MySQL driver, so the row-count
    query is a stub by default: pass a callable ``(host, port, query) -> int``
    built on a driver from a Lambda layer (pg8000, PyMySQL) and credentials
    from Secrets Manager to turn it on. Until then the RDS check proves the
    instance is available and accepting TCP connections, and says so.
    """

    def __init__(
        self,
        clients: dict[str, Any] | None = None,
        row_counter: Callable[[str, int, str], int] | None = None,
    ) -> None:
        self._clients = dict(clients or {})
        self._row_counter = row_counter

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            import boto3

            self._clients[service] = boto3.client(service)
        return self._clients[service]

    @staticmethod
    def _not_found(exc: Exception, codes: tuple[str, ...]) -> bool:
        response = getattr(exc, "response", None) or {}
        return response.get("Error", {}).get("Code") in codes

    # RDS
    def rds_instance(self, identifier: str) -> dict[str, Any]:
        try:
            response = self._client("rds").describe_db_instances(DBInstanceIdentifier=identifier)
        except Exception as exc:  # botocore ClientError, imported lazily
            if self._not_found(exc, ("DBInstanceNotFound", "DBInstanceNotFoundFault")):
                raise ResourceNotFound(identifier) from exc
            raise
        instance = response["DBInstances"][0]
        endpoint = instance.get("Endpoint") or {}
        return {
            "status": instance.get("DBInstanceStatus"),
            "host": endpoint.get("Address"),
            "port": endpoint.get("Port"),
        }

    def tcp_reachable(self, host: str, port: int, timeout: float) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def rds_row_count(self, host: str, port: int, query: str) -> int | None:
        if self._row_counter is None:
            return None
        return self._row_counter(host, port, query)

    # DynamoDB: Scan with Select=COUNT, not DescribeTable.ItemCount, which
    # AWS refreshes only about every six hours and reads 0 on a fresh restore.
    def dynamodb_count_items(self, table: str, stop_at: int) -> int:
        client = self._client("dynamodb")
        count, start_key = 0, None
        while True:
            kwargs: dict[str, Any] = {"TableName": table, "Select": "COUNT"}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            try:
                page = client.scan(**kwargs)
            except Exception as exc:
                if self._not_found(exc, ("ResourceNotFoundException",)):
                    raise ResourceNotFound(table) from exc
                raise
            count += page.get("Count", 0)
            start_key = page.get("LastEvaluatedKey")
            if count >= stop_at or not start_key:
                return count

    # S3
    def s3_count_objects(self, bucket: str, stop_at: int) -> int:
        client = self._client("s3")
        count, token = 0, None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                page = client.list_objects_v2(**kwargs)
            except Exception as exc:
                if self._not_found(exc, ("NoSuchBucket",)):
                    raise ResourceNotFound(bucket) from exc
                raise
            count += page.get("KeyCount", 0)
            token = page.get("NextContinuationToken")
            if count >= stop_at or not token:
                return count

    def s3_checksum_sample(self, bucket: str, sample_size: int) -> list[dict[str, Any]]:
        client = self._client("s3")
        listing = client.list_objects_v2(Bucket=bucket, MaxKeys=max(sample_size * 4, sample_size))
        results = []
        for obj in listing.get("Contents", []):
            if len(results) >= sample_size:
                break
            if obj.get("Size", 0) > MAX_CHECKSUM_OBJECT_BYTES:
                continue
            response = client.get_object(Bucket=bucket, Key=obj["Key"], ChecksumMode="ENABLED")
            body = response["Body"].read()
            results.append(_compare_checksum(obj["Key"], body, response))
        return results

    # EBS
    def ebs_volume(self, volume_id: str) -> dict[str, Any]:
        try:
            response = self._client("ec2").describe_volumes(VolumeIds=[volume_id])
        except Exception as exc:
            if self._not_found(exc, ("InvalidVolume.NotFound",)):
                raise ResourceNotFound(volume_id) from exc
            raise
        volume = response["Volumes"][0]
        return {"state": volume.get("State")}

    # Tags
    def tags(self, resource_type: str, resource_arn: str) -> dict[str, str]:
        if resource_type == "RDS":
            raw = self._client("rds").list_tags_for_resource(ResourceName=resource_arn).get("TagList", [])
        elif resource_type == "DynamoDB":
            raw = self._client("dynamodb").list_tags_of_resource(ResourceArn=resource_arn).get("Tags", [])
        elif resource_type == "S3":
            bucket = resource_id("S3", resource_arn)
            try:
                raw = self._client("s3").get_bucket_tagging(Bucket=bucket).get("TagSet", [])
            except Exception as exc:
                if self._not_found(exc, ("NoSuchTagSet",)):
                    return {}
                raise
        elif resource_type == "EBS":
            volume_id = resource_id("EBS", resource_arn)
            volume = self._client("ec2").describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
            raw = volume.get("Tags", [])
        else:
            return {}
        return {t["Key"]: t["Value"] for t in raw}

    def delete(self, resource_type: str, resource_arn: str) -> None:
        identifier = resource_id(resource_type, resource_arn)
        if resource_type == "RDS":
            self._client("rds").delete_db_instance(
                DBInstanceIdentifier=identifier, SkipFinalSnapshot=True, DeleteAutomatedBackups=True
            )
        elif resource_type == "DynamoDB":
            self._client("dynamodb").delete_table(TableName=identifier)
        elif resource_type == "EBS":
            self._client("ec2").delete_volume(VolumeId=identifier)
        else:
            raise ValueError(f"delete not supported for {resource_type}")


def _compare_checksum(key: str, body: bytes, response: dict[str, Any]) -> dict[str, Any]:
    """Recompute the object's checksum and compare it with what S3 stored.

    Prefers the additional SHA-256 checksum. Falls back to the ETag, which is
    the MD5 of the body only for single-part, non-KMS uploads. Composite
    (multipart) checksums can't be recomputed from the body alone and are
    reported as unverifiable rather than guessed at.
    """
    stored_sha = response.get("ChecksumSHA256")
    if stored_sha and "-" not in stored_sha:
        computed = base64.b64encode(hashlib.sha256(body).digest()).decode()
        return {"key": key, "algorithm": "SHA256", "stored": stored_sha, "computed": computed}
    etag = (response.get("ETag") or "").strip('"')
    if etag and "-" not in etag and response.get("ServerSideEncryption") != "aws:kms":
        return {"key": key, "algorithm": "MD5", "stored": etag, "computed": hashlib.md5(body).hexdigest()}
    return {"key": key, "algorithm": None, "stored": None, "computed": None}


# --------------------------------------------------------------------------
# In-memory fakes (tests)
# --------------------------------------------------------------------------


@dataclass
class FakeBackup:
    """Restore jobs keyed on ID, plus a record of reported validation results."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, str]] = field(default_factory=list)
    fail_put: bool = False

    def describe_restore_job(self, restore_job_id: str) -> dict[str, Any]:
        if restore_job_id not in self.jobs:
            raise KeyError(restore_job_id)
        return dict(self.jobs[restore_job_id])

    def put_restore_validation_result(self, restore_job_id: str, status: str, message: str) -> None:
        if self.fail_put:
            raise ConnectionError("simulated AWS Backup API failure")
        self.results.append({"RestoreJobId": restore_job_id, "ValidationStatus": status, "ValidationStatusMessage": message})


@dataclass
class FakeResources:
    """Restored resources keyed on ARN: {"type", "state", "tags", ...type-specific}."""

    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    reachable: bool = True
    row_count: int | None = None
    deleted: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def _get(self, resource_type: str, identifier: str) -> dict[str, Any]:
        for arn, res in self.resources.items():
            if res["type"] == resource_type and resource_id(resource_type, arn) == identifier:
                return res
        raise ResourceNotFound(identifier)

    def rds_instance(self, identifier: str) -> dict[str, Any]:
        self.calls.append(f"rds_instance:{identifier}")
        res = self._get("RDS", identifier)
        return {"status": res.get("state"), "host": res.get("host"), "port": res.get("port")}

    def tcp_reachable(self, host: str, port: int, timeout: float) -> bool:
        self.calls.append(f"tcp:{host}:{port}")
        return self.reachable

    def rds_row_count(self, host: str, port: int, query: str) -> int | None:
        self.calls.append(f"row_count:{query}")
        return self.row_count

    def dynamodb_count_items(self, table: str, stop_at: int) -> int:
        self.calls.append(f"ddb_count:{table}")
        return min(self._get("DynamoDB", table).get("items", 0), stop_at)

    def s3_count_objects(self, bucket: str, stop_at: int) -> int:
        self.calls.append(f"s3_count:{bucket}")
        return min(len(self._get("S3", bucket).get("objects", [])), stop_at)

    def s3_checksum_sample(self, bucket: str, sample_size: int) -> list[dict[str, Any]]:
        self.calls.append(f"s3_sample:{bucket}")
        return [dict(o) for o in self._get("S3", bucket).get("objects", [])[:sample_size]]

    def ebs_volume(self, volume_id: str) -> dict[str, Any]:
        self.calls.append(f"ebs:{volume_id}")
        return {"state": self._get("EBS", volume_id).get("state")}

    def tags(self, resource_type: str, resource_arn: str) -> dict[str, str]:
        res = self.resources.get(resource_arn)
        if res is None:
            raise ResourceNotFound(resource_arn)
        return dict(res.get("tags", {}))

    def delete(self, resource_type: str, resource_arn: str) -> None:
        self.deleted.append(resource_arn)
        self.resources.pop(resource_arn, None)
