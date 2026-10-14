"""The restore validator Lambda: per-type validation, reporting, metrics, cleanup."""

import unittest

from helpers import ARNS, PLAN_ARN, START, TAG, Harness, restore_event

from adapters import ResourceNotFound, resource_id
from handler import MAX_MESSAGE_LENGTH, cleanup, config_from_env, handle
from telemetry import METRIC_NAME, emf_record


def run(h, job_id="rj-1", status="COMPLETED"):
    return handle(restore_event(job_id, status), h.deps)


class ResourceTypeTests(unittest.TestCase):
    def assertVerdict(self, h, expected, *fragments):
        result = run(h)
        self.assertEqual(result["status"], expected, result)
        self.assertEqual(len(h.backup.results), 1)
        posted = h.backup.results[0]
        self.assertEqual(posted["RestoreJobId"], "rj-1")
        self.assertEqual(posted["ValidationStatus"], expected)
        for fragment in fragments:
            self.assertIn(fragment, posted["ValidationStatusMessage"])
        return posted

    # RDS
    def test_rds_success_with_row_count(self):
        h = Harness("RDS", rds_row_count_query="SELECT count(*) FROM orders", rds_min_rows=100)
        h.resources.row_count = 18234
        self.assertVerdict(h, "SUCCESSFUL", "status available", "reachable", "row count 18234 (minimum 100)")

    def test_rds_row_count_stub_is_reported_not_failed(self):
        h = Harness("RDS", rds_row_count_query="SELECT 1")
        h.resources.row_count = None  # no driver configured
        self.assertVerdict(h, "SUCCESSFUL", "row count skipped (no query runner configured)")

    def test_rds_no_query_configured_skips_row_count_call(self):
        h = Harness("RDS")
        self.assertVerdict(h, "SUCCESSFUL")
        self.assertFalse(any(c.startswith("row_count") for c in h.resources.calls))

    def test_rds_unreachable_fails(self):
        h = Harness("RDS")
        h.resources.reachable = False
        self.assertVerdict(h, "FAILED", "FAIL: endpoint restored.example.internal:5432 unreachable")

    def test_rds_not_available_fails(self):
        h = Harness("RDS")
        h.resources.resources[ARNS["RDS"]]["state"] = "incompatible-restore"
        self.assertVerdict(h, "FAILED", "FAIL: instance awsbackup-restore-test-orders-db status incompatible-restore")

    def test_rds_too_few_rows_fails(self):
        h = Harness("RDS", rds_row_count_query="SELECT count(*) FROM orders", rds_min_rows=100)
        h.resources.row_count = 3
        self.assertVerdict(h, "FAILED", "FAIL: row count 3 (minimum 100)")

    def test_rds_without_endpoint_fails(self):
        h = Harness("RDS")
        h.resources.resources[ARNS["RDS"]]["host"] = None
        self.assertVerdict(h, "FAILED", "instance has no endpoint")

    # DynamoDB
    def test_dynamodb_success(self):
        h = Harness("DynamoDB", dynamodb_min_items=1000)
        self.assertVerdict(h, "SUCCESSFUL", ">= 1000 items (minimum 1000)")

    def test_dynamodb_below_threshold_fails(self):
        h = Harness("DynamoDB", dynamodb_min_items=5000)
        self.assertVerdict(h, "FAILED", "FAIL: table awsbackup-restore-test-sessions has >= 1200 items (minimum 5000)")

    def test_dynamodb_empty_table_fails(self):
        h = Harness("DynamoDB")
        h.resources.resources[ARNS["DynamoDB"]]["items"] = 0
        self.assertVerdict(h, "FAILED", "has >= 0 items")

    # S3
    def test_s3_success_counts_and_checksums(self):
        h = Harness("S3", s3_min_objects=5, s3_checksum_sample=4)
        self.assertVerdict(h, "SUCCESSFUL", ">= 5 objects", "checksums match on 4/4 sampled objects")

    def test_s3_checksum_mismatch_fails(self):
        h = Harness("S3")
        h.resources.resources[ARNS["S3"]]["objects"][1]["computed"] = "different="
        self.assertVerdict(h, "FAILED", "FAIL: checksum mismatch on 1/5 sampled objects: img/1.png")

    def test_s3_too_few_objects_fails(self):
        h = Harness("S3", s3_min_objects=50)
        self.assertVerdict(h, "FAILED", "FAIL: bucket awsbackup-restore-test-media-assets-0001 has >= 8 objects (minimum 50)")

    def test_s3_unverifiable_sample_is_reported_not_failed(self):
        h = Harness("S3")
        for obj in h.resources.resources[ARNS["S3"]]["objects"]:
            obj.update(algorithm=None, stored=None, computed=None)
        self.assertVerdict(h, "SUCCESSFUL", "no verifiable checksum in 5 sampled objects")

    # EBS
    def test_ebs_available_succeeds(self):
        self.assertVerdict(Harness("EBS"), "SUCCESSFUL", "volume vol-0example0000restore state available")

    def test_ebs_error_state_fails(self):
        h = Harness("EBS")
        h.resources.resources[ARNS["EBS"]]["state"] = "error"
        self.assertVerdict(h, "FAILED", "FAIL: volume vol-0example0000restore state error")

    # Errors
    def test_missing_restored_resource_fails(self):
        h = Harness()
        h.backup.jobs["rj-1"] = {"RestoreJobId": "rj-1", "ResourceType": "EBS", "CreatedResourceArn": ARNS["EBS"],
                                 "CreatedBy": {"RestoreTestingPlanArn": PLAN_ARN}}
        self.assertVerdict(h, "FAILED", "restored resource not found")

    def test_probe_exception_becomes_failed_verdict(self):
        h = Harness("DynamoDB")

        def boom(table, stop_at):
            raise TimeoutError("scan timed out")

        h.resources.dynamodb_count_items = boom
        self.assertVerdict(h, "FAILED", "validation error TimeoutError: scan timed out")

    def test_message_is_truncated(self):
        h = Harness("S3")
        h.resources.resources[ARNS["S3"]]["objects"] = [
            {"key": "k" * 600 + str(i), "algorithm": "SHA256", "stored": "a", "computed": "b"} for i in range(5)
        ]
        posted = self.assertVerdict(h, "FAILED")
        self.assertLessEqual(len(posted["ValidationStatusMessage"]), MAX_MESSAGE_LENGTH)


class RoutingTests(unittest.TestCase):
    def test_non_completed_status_is_ignored(self):
        h = Harness("EBS")
        result = run(h, status="FAILED")
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(h.backup.results, [])

    def test_manual_restore_is_not_validated(self):
        h = Harness()
        h.add("RDS", test=False)
        result = run(h)
        self.assertEqual(result, {"status": "ignored", "reason": "not a restore-testing job", "restoreJobId": "rj-1"})
        self.assertEqual(h.backup.results, [])
        self.assertEqual(h.resources.calls, [])

    def test_unsupported_type_is_skipped_without_verdict(self):
        h = Harness()
        h.backup.jobs["rj-1"] = {"RestoreJobId": "rj-1", "ResourceType": "EFS",
                                 "CreatedResourceArn": "arn:aws:elasticfilesystem:us-west-2:123456789012:file-system/fs-0example",
                                 "CreatedBy": {"RestoreTestingPlanArn": PLAN_ARN}}
        self.assertEqual(run(h)["status"], "skipped")
        self.assertEqual(h.backup.results, [])
        self.assertEqual(h.emf(), [])

    def test_event_without_job_id_is_ignored(self):
        h = Harness()
        self.assertEqual(handle({"detail": {}}, h.deps)["status"], "ignored")

    def test_put_failure_propagates_so_lambda_retries(self):
        h = Harness("EBS")
        h.backup.fail_put = True
        with self.assertRaises(ConnectionError):
            run(h)


class TelemetryTests(unittest.TestCase):
    def test_emf_line_shape_on_success(self):
        h = Harness("DynamoDB")
        run(h)
        (emf,) = h.emf()
        directive = emf["_aws"]
        self.assertEqual(directive["Timestamp"], int(START * 1000))
        (metrics,) = directive["CloudWatchMetrics"]
        self.assertEqual(metrics["Namespace"], "BackupDR/RestoreTesting")
        self.assertEqual(metrics["Dimensions"], [["ResourceType"]])
        self.assertEqual(metrics["Metrics"], [{"Name": METRIC_NAME, "Unit": "Count"}])
        self.assertEqual(emf["ResourceType"], "DynamoDB")
        self.assertEqual(emf[METRIC_NAME], 1)
        self.assertEqual(emf["restoreJobId"], "rj-1")
        # every dimension and metric named in the directive is a top-level member
        for name in metrics["Dimensions"][0] + [m["Name"] for m in metrics["Metrics"]]:
            self.assertIn(name, emf)

    def test_emf_value_zero_on_failure(self):
        h = Harness("EBS")
        h.resources.resources[ARNS["EBS"]]["state"] = "error"
        run(h)
        self.assertEqual(h.emf()[0][METRIC_NAME], 0)

    def test_custom_namespace(self):
        record = emf_record(namespace="Custom/NS", resource_type="S3", succeeded=True, epoch_seconds=1.5)
        self.assertEqual(record["_aws"]["CloudWatchMetrics"][0]["Namespace"], "Custom/NS")
        self.assertEqual(record["_aws"]["Timestamp"], 1500)

    def test_structured_log_record(self):
        h = Harness("RDS")
        h.resources.reachable = False
        run(h)
        logs = [line for line in h.lines() if "_aws" not in line]
        (record,) = logs
        self.assertEqual(record["level"], "ERROR")
        self.assertEqual(record["service"], "restore-validator")
        self.assertEqual(record["message"], "restore validation failed")
        self.assertEqual(record["timestamp"], "2026-10-14T06:00:00.000Z")
        self.assertEqual(record["restore_job_id"], "rj-1")
        self.assertEqual(record["validation_status"], "FAILED")
        self.assertEqual(record["restore_testing_plan_arn"], PLAN_ARN)
        self.assertIsInstance(record["checks"], list)


class CleanupTests(unittest.TestCase):
    def test_refuses_untagged_resource(self):
        h = Harness("RDS", tagged=False)
        result = cleanup("RDS", ARNS["RDS"], h.deps)
        self.assertEqual(result.action, "refused")
        self.assertIn(TAG, result.reason)
        self.assertEqual(h.resources.deleted, [])

    def test_deletes_tagged_resource(self):
        h = Harness("DynamoDB")
        self.assertEqual(cleanup("DynamoDB", ARNS["DynamoDB"], h.deps).action, "deleted")
        self.assertEqual(h.resources.deleted, [ARNS["DynamoDB"]])

    def test_s3_is_never_deleted_by_the_function(self):
        h = Harness("S3")
        self.assertEqual(cleanup("S3", ARNS["S3"], h.deps).action, "unsupported")
        self.assertEqual(h.resources.deleted, [])

    def test_missing_resource(self):
        h = Harness()
        self.assertEqual(cleanup("EBS", ARNS["EBS"], h.deps).action, "not_found")

    def test_custom_tag_key_is_honoured(self):
        h = Harness("EBS", restore_test_tag_key="restore-test-owner")
        self.assertEqual(cleanup("EBS", ARNS["EBS"], h.deps).action, "refused")

    def test_handler_runs_cleanup_only_when_enabled(self):
        off = Harness("EBS")
        self.assertNotIn("cleanup", run(off))
        self.assertEqual(off.resources.deleted, [])

        on = Harness("EBS", early_cleanup=True)
        self.assertEqual(run(on)["cleanup"], "deleted")

        untagged = Harness("EBS", tagged=False, early_cleanup=True)
        result = run(untagged)
        self.assertEqual(result["status"], "SUCCESSFUL")
        self.assertEqual(result["cleanup"], "refused")
        self.assertEqual(untagged.resources.deleted, [])


class ConfigAndArnTests(unittest.TestCase):
    def test_config_from_env(self):
        cfg = config_from_env({"DYNAMODB_MIN_ITEMS": "50", "S3_CHECKSUM_SAMPLE": "0", "EARLY_CLEANUP": "TRUE",
                               "RESTORE_TEST_TAG_KEY": "x", "METRIC_NAMESPACE": "N"})
        self.assertEqual((cfg.dynamodb_min_items, cfg.s3_checksum_sample, cfg.early_cleanup), (50, 0, True))
        self.assertEqual((cfg.restore_test_tag_key, cfg.metric_namespace), ("x", "N"))

    def test_config_defaults(self):
        cfg = config_from_env({})
        self.assertFalse(cfg.early_cleanup)
        self.assertEqual(cfg.restore_test_tag_key, TAG)

    def test_resource_id(self):
        self.assertEqual(resource_id("RDS", ARNS["RDS"]), "awsbackup-restore-test-orders-db")
        self.assertEqual(resource_id("DynamoDB", ARNS["DynamoDB"]), "awsbackup-restore-test-sessions")
        self.assertEqual(resource_id("S3", ARNS["S3"]), "awsbackup-restore-test-media-assets-0001")
        self.assertEqual(resource_id("EBS", ARNS["EBS"]), "vol-0example0000restore")

    def test_resource_id_rejects_bad_arns(self):
        with self.assertRaises(ValueError):
            resource_id("RDS", "arn:aws:rds:us-west-2:123456789012:cluster:aurora-1")
        with self.assertRaises(ValueError):
            resource_id("EFS", "arn:aws:elasticfilesystem:::x")

    def test_fake_raises_not_found(self):
        h = Harness()
        with self.assertRaises(ResourceNotFound):
            h.resources.ebs_volume("vol-missing")


if __name__ == "__main__":
    unittest.main()
