"""The boto3 adapters, driven by stub clients so boto3 is never imported."""

import base64
import hashlib
import io
import sys
import unittest

import helpers  # noqa: F401  (import path)

from adapters import Boto3Backup, Boto3Resources, ResourceNotFound, _compare_checksum


class StubClient:
    """Records calls; returns queued responses or raises queued errors per method."""

    def __init__(self, **responses):
        self.responses = {name: list(items) for name, items in responses.items()}
        self.calls = []

    def __getattr__(self, name):
        def method(**kwargs):
            self.calls.append((name, kwargs))
            item = self.responses[name].pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return method


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class Boto3BackupTests(unittest.TestCase):
    def test_put_restore_validation_result_arguments(self):
        client = StubClient(put_restore_validation_result=[{}])
        Boto3Backup(client).put_restore_validation_result("rj-1", "FAILED", "volume state error")
        self.assertEqual(client.calls, [("put_restore_validation_result",
                                         {"RestoreJobId": "rj-1", "ValidationStatus": "FAILED",
                                          "ValidationStatusMessage": "volume state error"})])

    def test_describe_restore_job(self):
        client = StubClient(describe_restore_job=[{"RestoreJobId": "rj-1"}])
        self.assertEqual(Boto3Backup(client).describe_restore_job("rj-1"), {"RestoreJobId": "rj-1"})

    def test_boto3_not_imported_by_the_suite(self):
        self.assertNotIn("boto3", sys.modules)


class Boto3ResourcesTests(unittest.TestCase):
    def test_dynamodb_count_paginates_and_stops_early(self):
        ddb = StubClient(scan=[{"Count": 400, "LastEvaluatedKey": {"pk": "a"}},
                               {"Count": 700, "LastEvaluatedKey": {"pk": "b"}},
                               {"Count": 999}])
        count = Boto3Resources({"dynamodb": ddb}).dynamodb_count_items("t", stop_at=1000)
        self.assertEqual(count, 1100)
        self.assertEqual(len(ddb.calls), 2)
        self.assertEqual(ddb.calls[1][1]["ExclusiveStartKey"], {"pk": "a"})
        self.assertEqual(ddb.calls[0][1]["Select"], "COUNT")

    def test_dynamodb_not_found(self):
        ddb = StubClient(scan=[ClientError("ResourceNotFoundException")])
        with self.assertRaises(ResourceNotFound):
            Boto3Resources({"dynamodb": ddb}).dynamodb_count_items("t", stop_at=1)

    def test_other_errors_propagate(self):
        ddb = StubClient(scan=[ClientError("AccessDeniedException")])
        with self.assertRaises(ClientError):
            Boto3Resources({"dynamodb": ddb}).dynamodb_count_items("t", stop_at=1)

    def test_s3_count_paginates(self):
        s3 = StubClient(list_objects_v2=[{"KeyCount": 1000, "NextContinuationToken": "n"}, {"KeyCount": 3}])
        self.assertEqual(Boto3Resources({"s3": s3}).s3_count_objects("b", stop_at=5000), 1003)

    def test_s3_checksum_sample_skips_large_objects(self):
        body = b"hello"
        sha = base64.b64encode(hashlib.sha256(body).digest()).decode()
        s3 = StubClient(
            list_objects_v2=[{"Contents": [{"Key": "big", "Size": 10**9}, {"Key": "small", "Size": 5}]}],
            get_object=[{"Body": io.BytesIO(body), "ChecksumSHA256": sha}],
        )
        (result,) = Boto3Resources({"s3": s3}).s3_checksum_sample("b", 2)
        self.assertEqual(result["key"], "small")
        self.assertEqual(result["stored"], result["computed"])
        self.assertEqual(s3.calls[1][1]["ChecksumMode"], "ENABLED")

    def test_rds_instance_and_not_found(self):
        rds = StubClient(describe_db_instances=[
            {"DBInstances": [{"DBInstanceStatus": "available", "Endpoint": {"Address": "h", "Port": 3306}}]},
            ClientError("DBInstanceNotFound"),
        ])
        res = Boto3Resources({"rds": rds})
        self.assertEqual(res.rds_instance("db1"), {"status": "available", "host": "h", "port": 3306})
        with self.assertRaises(ResourceNotFound):
            res.rds_instance("db2")

    def test_row_count_stub_and_hook(self):
        self.assertIsNone(Boto3Resources({}).rds_row_count("h", 1, "q"))
        self.assertEqual(Boto3Resources({}, row_counter=lambda h, p, q: 42).rds_row_count("h", 1, "q"), 42)

    def test_tcp_unreachable_returns_false(self):
        # Port 9 on a documentation-range address: no route, short timeout.
        self.assertFalse(Boto3Resources({}).tcp_reachable("192.0.2.1", 9, timeout=0.2))

    def test_tags_normalised(self):
        ec2 = StubClient(describe_volumes=[{"Volumes": [{"Tags": [{"Key": "a", "Value": "1"}]}]}])
        tags = Boto3Resources({"ec2": ec2}).tags("EBS", "arn:aws:ec2:us-west-2:123456789012:volume/vol-1")
        self.assertEqual(tags, {"a": "1"})
        self.assertEqual(ec2.calls[0][1], {"VolumeIds": ["vol-1"]})

    def test_s3_without_tag_set(self):
        s3 = StubClient(get_bucket_tagging=[ClientError("NoSuchTagSet")])
        self.assertEqual(Boto3Resources({"s3": s3}).tags("S3", "arn:aws:s3:::b"), {})

    def test_delete_rds_skips_final_snapshot(self):
        rds = StubClient(delete_db_instance=[{}])
        Boto3Resources({"rds": rds}).delete("RDS", "arn:aws:rds:us-west-2:123456789012:db:restored-1")
        self.assertEqual(rds.calls[0][1]["DBInstanceIdentifier"], "restored-1")
        self.assertTrue(rds.calls[0][1]["SkipFinalSnapshot"])


class ChecksumTests(unittest.TestCase):
    body = b"backup payload"

    def test_sha256_match_and_mismatch(self):
        sha = base64.b64encode(hashlib.sha256(self.body).digest()).decode()
        ok = _compare_checksum("k", self.body, {"ChecksumSHA256": sha})
        self.assertEqual((ok["algorithm"], ok["stored"] == ok["computed"]), ("SHA256", True))
        bad = _compare_checksum("k", self.body + b"!", {"ChecksumSHA256": sha})
        self.assertNotEqual(bad["stored"], bad["computed"])

    def test_md5_etag_fallback(self):
        etag = '"' + hashlib.md5(self.body).hexdigest() + '"'
        res = _compare_checksum("k", self.body, {"ETag": etag})
        self.assertEqual((res["algorithm"], res["stored"] == res["computed"]), ("MD5", True))

    def test_multipart_and_kms_are_unverifiable(self):
        self.assertIsNone(_compare_checksum("k", self.body, {"ETag": '"abc-3"'})["algorithm"])
        self.assertIsNone(_compare_checksum("k", self.body, {"ChecksumSHA256": "abc=-2"})["algorithm"])
        kms = {"ETag": '"' + hashlib.md5(self.body).hexdigest() + '"', "ServerSideEncryption": "aws:kms"}
        self.assertIsNone(_compare_checksum("k", self.body, kms)["algorithm"])


if __name__ == "__main__":
    unittest.main()
