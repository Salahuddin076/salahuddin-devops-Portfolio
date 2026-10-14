"""Real adapters through stub clients and a stub process runner (no AWS, no cluster)."""

import json
import subprocess
import unittest
import urllib.error
from datetime import datetime, timezone

from helpers import DR, GCID, PRIMARY, config

from failover.aws import AuroraGlobal, HelmWorkload, HttpHealth, Route53Failover, _Clients
from failover.ports import Unreachable

ARN = {
    PRIMARY: "arn:aws:rds:us-east-1:123456789012:cluster:dr-app-us-east-1",
    DR: "arn:aws:rds:us-west-2:123456789012:cluster:dr-app-us-west-2",
}


class StubRds:
    def __init__(self, region, world):
        self.region = region
        self.world = world
        self.calls = []

    def describe_global_clusters(self, **kw):
        self.calls.append(("describe_global_clusters", kw))
        if self.world.get("down") == self.region:
            raise ConnectionError("endpoint timeout")
        return {"GlobalClusters": [{"GlobalClusterMembers": [
            {"DBClusterArn": ARN[r], "IsWriter": r == self.world["writer"]} for r in self.world["members"]
        ]}]}

    def describe_db_clusters(self, **kw):
        self.calls.append(("describe_db_clusters", kw))
        attached = self.region in self.world["members"]
        return {"DBClusters": [{"Status": "available",
                                **({"GlobalClusterIdentifier": GCID} if attached else {})}]}

    def failover_global_cluster(self, **kw):
        self.calls.append(("failover_global_cluster", kw))
        self.world["writer"] = self.region

    def remove_from_global_cluster(self, **kw):
        self.calls.append(("remove_from_global_cluster", kw))
        self.world["members"].remove(self.region)


class StubCloudWatch:
    def __init__(self, points):
        self.points = points
        self.calls = []

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        return {"Datapoints": self.points}


class StubRoute53:
    def __init__(self):
        self.calls = []
        self.records = [
            {"Name": "orders.example.com.", "Type": "A", "SetIdentifier": PRIMARY, "Failover": "PRIMARY",
             "HealthCheckId": "hc-1", "AliasTarget": {"DNSName": "alb-1", "HostedZoneId": "Z1",
                                                      "EvaluateTargetHealth": True}},
            {"Name": "orders.example.com.", "Type": "A", "SetIdentifier": DR, "Failover": "SECONDARY",
             "HealthCheckId": "hc-2", "AliasTarget": {"DNSName": "alb-2", "HostedZoneId": "Z2",
                                                      "EvaluateTargetHealth": True}},
            {"Name": "us-east-1.orders.example.com.", "Type": "A"},
        ]

    def list_resource_record_sets(self, **kw):
        self.calls.append(("list", kw))
        return {"ResourceRecordSets": self.records}

    def change_resource_record_sets(self, **kw):
        self.calls.append(("change", kw))


class AuroraGlobalTests(unittest.TestCase):
    def setUp(self):
        self.world = {"writer": PRIMARY, "members": [PRIMARY, DR]}
        self.rds = {r: StubRds(r, self.world) for r in (PRIMARY, DR)}
        self.cw = StubCloudWatch([
            {"Timestamp": datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc), "Maximum": 900.0},
            {"Timestamp": datetime(2026, 10, 14, 9, 1, tzinfo=timezone.utc), "Maximum": 350.0},
        ])
        clients = _Clients(lambda svc, region: self.cw if svc == "cloudwatch" else self.rds[region])
        self.db = AuroraGlobal(config(), clients, sleep=lambda s: None, poll_s=0)

    def test_global_cluster_reads_writer_from_dr_region_first(self):
        gc = self.db.global_cluster()
        self.assertEqual((gc.writer_region, gc.members), (PRIMARY, (PRIMARY, DR)))
        self.assertEqual(len(self.rds[DR].calls), 1)
        self.assertEqual(self.rds[PRIMARY].calls, [])

    def test_falls_back_to_primary_region_api(self):
        self.world["down"] = DR
        self.assertEqual(self.db.global_cluster().writer_region, PRIMARY)

    def test_lag_is_latest_datapoint_in_seconds(self):
        self.assertEqual(self.db.replication_lag_seconds(DR), 0.35)
        kw = self.cw.calls[0]
        self.assertEqual(kw["MetricName"], "AuroraGlobalDBReplicationLag")
        self.assertEqual(kw["Dimensions"], [{"Name": "DBClusterIdentifier", "Value": "dr-app-us-west-2"}])

    def test_lag_none_without_datapoints(self):
        self.cw.points = []
        self.assertIsNone(self.db.replication_lag_seconds(DR))

    def test_switchover_uses_managed_switchover(self):
        self.db.switchover(DR)
        name, kw = next(c for c in self.rds[DR].calls if c[0] == "failover_global_cluster")
        self.assertEqual(kw, {"GlobalClusterIdentifier": GCID, "TargetDbClusterIdentifier": ARN[DR],
                              "Switchover": True})
        self.assertNotIn("AllowDataLoss", kw)

    def test_detach_and_promote(self):
        self.db.detach_and_promote(DR)
        name, kw = next(c for c in self.rds[DR].calls if c[0] == "remove_from_global_cluster")
        self.assertEqual(kw, {"GlobalClusterIdentifier": GCID, "DbClusterIdentifier": ARN[DR]})
        self.assertEqual(self.db.writers(), [PRIMARY, DR])  # two writers until the old one is fenced


class Route53Tests(unittest.TestCase):
    def test_active_region_and_atomic_swap(self):
        r53 = StubRoute53()
        dns = Route53Failover(config(), _Clients(lambda svc, region: r53))
        self.assertEqual(dns.active_region(), PRIMARY)
        dns.set_active(DR)
        changes = [c for c in r53.calls if c[0] == "change"]
        self.assertEqual(len(changes), 1)  # one batch
        batch = changes[0][1]["ChangeBatch"]["Changes"]
        roles = {c["ResourceRecordSet"]["SetIdentifier"]: c["ResourceRecordSet"]["Failover"] for c in batch}
        self.assertEqual(roles, {PRIMARY: "SECONDARY", DR: "PRIMARY"})
        self.assertTrue(all(c["Action"] == "UPSERT" for c in batch))
        # alias targets and health checks are preserved
        self.assertEqual(batch[1]["ResourceRecordSet"]["HealthCheckId"], "hc-2")

    def test_refuses_when_records_missing(self):
        r53 = StubRoute53()
        r53.records = r53.records[:1]
        dns = Route53Failover(config(), _Clients(lambda svc, region: r53))
        with self.assertRaises(RuntimeError):
            dns.set_active(DR)


def proc(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class HelmWorkloadTests(unittest.TestCase):
    def test_fence_sets_workers_disabled(self):
        cmds = []
        w = HelmWorkload(config(), runner=lambda cmd: cmds.append(cmd) or proc())
        w.set_scale(PRIMARY, workers=0)
        cmd = cmds[0]
        self.assertEqual(cmd[:4], ["helm", "upgrade", "dr-app", "helm/dr-app"])
        self.assertIn("--reuse-values", cmd)
        self.assertEqual(cmd[cmd.index("--set") + 1], "workers.enabled=false")
        self.assertEqual(cmd[cmd.index("--kube-context") + 1],
                         "arn:aws:eks:us-east-1:123456789012:cluster/dr-app-us-east-1-eks")

    def test_scale_up_sets_hpa_min_and_workers(self):
        cmds = []
        w = HelmWorkload(config(), runner=lambda cmd: cmds.append(cmd) or proc())
        w.set_scale(DR, api_min_replicas=3, workers=2)
        self.assertEqual(cmds[0][cmds[0].index("--set") + 1],
                         "api.autoscaling.minReplicas=3,workers.enabled=true,workers.replicas=2")

    def test_unreachable_cluster_maps_to_unreachable(self):
        w = HelmWorkload(config(), runner=lambda cmd: proc(1, err="Error: Kubernetes cluster unreachable"))
        with self.assertRaises(Unreachable):
            w.set_scale(PRIMARY, workers=0)
        with self.assertRaises(Unreachable):
            w.get_scale(PRIMARY)

    def test_other_helm_errors_are_not_unreachable(self):
        w = HelmWorkload(config(), runner=lambda cmd: proc(1, err="Error: UPGRADE FAILED: values don't meet schema"))
        with self.assertRaises(RuntimeError) as ctx:
            w.set_scale(PRIMARY, workers=0)
        self.assertNotIsInstance(ctx.exception, Unreachable)

    def test_get_scale_reads_hpa_and_worker_deployment(self):
        def runner(cmd):
            kind = cmd[cmd.index("get") + 1]
            body = {"spec": {"minReplicas": 2}} if kind == "hpa" else {"spec": {"replicas": 0}}
            return proc(0, json.dumps(body))

        s = HelmWorkload(config(), runner=runner).get_scale(DR)
        self.assertEqual((s.api_min_replicas, s.workers), (2, 0))


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class HttpHealthTests(unittest.TestCase):
    def check(self, opener):
        return HttpHealth(config(), opener=opener).check(DR)

    def test_200_is_healthy(self):
        h = self.check(lambda url, timeout: FakeResponse(200))
        self.assertEqual((h.reachable, h.healthy), (True, True))

    def test_http_error_is_reachable_but_unhealthy(self):
        def opener(url, timeout):
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

        h = self.check(opener)
        self.assertEqual((h.reachable, h.healthy), (True, False))
        self.assertIn("503", h.detail)

    def test_connection_error_is_unreachable(self):
        def opener(url, timeout):
            raise urllib.error.URLError("timed out")

        self.assertEqual(self.check(opener).reachable, False)


if __name__ == "__main__":
    unittest.main()
