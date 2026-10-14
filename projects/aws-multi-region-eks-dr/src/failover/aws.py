"""Real adapters: boto3 for RDS, CloudWatch and Route 53, urllib for health,
helm/kubectl through subprocess for the workload.

boto3 is imported lazily (inside `_client`), so importing this module, and
the whole test suite, needs only the standard library. Clients can be
injected for tests; the defaults build one client per service and region.

None of this has been run against AWS: API names and parameters follow the
boto3 documentation and are listed as unverified in the README.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from failover.config import Config
from failover.ports import Adapters, GlobalCluster, Health, Scale, Unreachable


def _client(service: str, region: str):
    import boto3  # lazy: only when --adapters aws is used

    return boto3.client(service, region_name=region)


def _region_of(arn: str) -> str:
    # arn:aws:rds:us-west-2:123456789012:cluster:name
    return arn.split(":")[3]


class _Clients:
    def __init__(self, factory: Callable[[str, str], Any] = _client) -> None:
        self._factory = factory
        self._cache: dict[tuple[str, str], Any] = {}

    def get(self, service: str, region: str):
        key = (service, region)
        if key not in self._cache:
            self._cache[key] = self._factory(service, region)
        return self._cache[key]


# --------------------------------------------------------------------------
# Health: the region's own hostname, deep path
# --------------------------------------------------------------------------


class HttpHealth:
    def __init__(self, config: Config, timeout: float = 5.0,
                 opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.config = config
        self.timeout = timeout
        self._open = opener

    def check(self, region: str) -> Health:
        url = self.config.regions[region].health_url
        try:
            with self._open(url, timeout=self.timeout) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            exc.close()
            return Health(True, False, f"HTTP {exc.code} from {url}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return Health(False, False, f"{type(exc).__name__}: {exc}")
        return Health(True, code == 200, f"HTTP {code} from {url}")


# --------------------------------------------------------------------------
# Aurora Global Database
# --------------------------------------------------------------------------


class AuroraGlobal:
    def __init__(self, config: Config, clients: Optional[_Clients] = None,
                 sleep: Callable[[float], None] = time.sleep, timeout_s: float = 1800,
                 poll_s: float = 15) -> None:
        self.config = config
        self.clients = clients or _Clients()
        self.sleep = sleep
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def _describe_global(self) -> dict[str, Any]:
        # Ask the DR region first: during a primary outage its API still answers.
        last: Optional[Exception] = None
        for region in (self.config.dr_region, self.config.primary_region):
            try:
                rds = self.clients.get("rds", region)
                resp = rds.describe_global_clusters(GlobalClusterIdentifier=self.config.global_cluster_id)
                return resp["GlobalClusters"][0]
            except Exception as exc:  # noqa: BLE001 - try the other region
                last = exc
        raise Unreachable(f"describe_global_clusters failed in both regions: {last}")

    def global_cluster(self) -> GlobalCluster:
        g = self._describe_global()
        members = g.get("GlobalClusterMembers", [])
        writer = next((_region_of(m["DBClusterArn"]) for m in members if m.get("IsWriter")), None)
        return GlobalCluster(writer, tuple(_region_of(m["DBClusterArn"]) for m in members))

    def _standalone_writable(self, region: str) -> bool:
        rc = self.config.regions[region]
        try:
            rds = self.clients.get("rds", region)
            c = rds.describe_db_clusters(DBClusterIdentifier=rc.cluster_id)["DBClusters"][0]
        except Exception:  # noqa: BLE001 - unreachable region: unknown, not a writer we can see
            return False
        return c.get("Status") == "available" and not c.get("GlobalClusterIdentifier")

    def writers(self) -> list[str]:
        gc = self.global_cluster()
        out = [gc.writer_region] if gc.writer_region else []
        for region in self.config.regions:
            if region not in gc.members and region not in out and self._standalone_writable(region):
                out.append(region)
        return out

    def replication_lag_seconds(self, region: str) -> Optional[float]:
        cw = self.clients.get("cloudwatch", region)
        now = datetime.now(timezone.utc)
        resp = cw.get_metric_statistics(
            Namespace="AWS/RDS",
            MetricName="AuroraGlobalDBReplicationLag",
            Dimensions=[{"Name": "DBClusterIdentifier", "Value": self.config.regions[region].cluster_id}],
            StartTime=now - timedelta(minutes=5),
            EndTime=now,
            Period=60,
            Statistics=["Maximum"],
        )
        points = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
        return points[-1]["Maximum"] / 1000.0 if points else None

    def _wait(self, done: Callable[[], bool], what: str) -> None:
        deadline = time.monotonic() + self.timeout_s
        while not done():
            if time.monotonic() > deadline:
                raise TimeoutError(f"timed out waiting for {what}")
            self.sleep(self.poll_s)

    def switchover(self, target_region: str) -> None:
        rc = self.config.regions[target_region]
        rds = self.clients.get("rds", target_region)
        # Managed switchover: the global cluster waits for the target to catch
        # up, swaps roles, keeps the topology. Equivalent to
        # switchover_global_cluster in newer API versions.
        rds.failover_global_cluster(
            GlobalClusterIdentifier=self.config.global_cluster_id,
            TargetDbClusterIdentifier=rc.cluster_arn,
            Switchover=True,
        )
        self._wait(lambda: self.global_cluster().writer_region == target_region, f"{target_region} to become writer")

    def detach_and_promote(self, target_region: str) -> None:
        rc = self.config.regions[target_region]
        rds = self.clients.get("rds", target_region)
        rds.remove_from_global_cluster(
            GlobalClusterIdentifier=self.config.global_cluster_id,
            DbClusterIdentifier=rc.cluster_arn,
        )
        self._wait(lambda: self._standalone_writable(target_region), f"{rc.cluster_id} to become a standalone writer")


# --------------------------------------------------------------------------
# Route 53 failover records
# --------------------------------------------------------------------------


class Route53Failover:
    def __init__(self, config: Config, clients: Optional[_Clients] = None) -> None:
        self.config = config
        self.clients = clients or _Clients()

    @property
    def _r53(self):
        # Route 53's control plane is in us-east-1 whatever region you call.
        return self.clients.get("route53", "us-east-1")

    def _records(self) -> list[dict[str, Any]]:
        if not self.config.hosted_zone_id or not self.config.record_name:
            return []
        name = self.config.record_name.rstrip(".") + "."
        resp = self._r53.list_resource_record_sets(
            HostedZoneId=self.config.hosted_zone_id, StartRecordName=name, StartRecordType="A", MaxItems="10")
        return [r for r in resp["ResourceRecordSets"]
                if r["Name"] == name and r["Type"] == "A" and r.get("Failover")]

    def active_region(self) -> Optional[str]:
        return next((r["SetIdentifier"] for r in self._records() if r["Failover"] == "PRIMARY"), None)

    def set_active(self, region: str) -> None:
        records = self._records()
        if {r["SetIdentifier"] for r in records} != set(self.config.regions):
            raise RuntimeError(f"expected failover records for {sorted(self.config.regions)}, found "
                               f"{sorted(r['SetIdentifier'] for r in records)}")
        changes = []
        for r in records:
            new = dict(r)
            new["Failover"] = "PRIMARY" if r["SetIdentifier"] == region else "SECONDARY"
            changes.append({"Action": "UPSERT", "ResourceRecordSet": new})
        # One batch: Route 53 applies it atomically, so there is never a
        # moment with two PRIMARY records or none.
        self._r53.change_resource_record_sets(
            HostedZoneId=self.config.hosted_zone_id,
            ChangeBatch={"Comment": f"failover: {region} PRIMARY", "Changes": changes},
        )


# --------------------------------------------------------------------------
# Workload: helm upgrade --reuse-values, read back with kubectl
# --------------------------------------------------------------------------


Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)


class HelmWorkload:
    """Changes only the three values the failover owns, keeping everything else
    as deployed (`--reuse-values`). Assumes an authenticated kube context per
    region (aws eks update-kubeconfig). A kubectl failure to connect means
    the region is unreachable."""

    def __init__(self, config: Config, runner: Runner = _run) -> None:
        self.config = config
        self.run = runner

    def _kubectl(self, region: str, *args: str) -> dict[str, Any]:
        rc = self.config.regions[region]
        cmd = ["kubectl", "--context", rc.kube_context, "--namespace", rc.namespace,
               "--request-timeout", "10s", *args, "-o", "json"]
        proc = self.run(cmd)
        if proc.returncode != 0:
            raise Unreachable(f"{region}: kubectl failed: {proc.stderr.strip()[:200]}")
        return json.loads(proc.stdout)

    def get_scale(self, region: str) -> Scale:
        rc = self.config.regions[region]
        hpa = self._kubectl(region, "get", "hpa", f"{rc.release}-api")
        worker = self._kubectl(region, "get", "deployment", f"{rc.release}-worker")
        return Scale(int(hpa["spec"]["minReplicas"]), int(worker["spec"].get("replicas", 0)))

    def set_scale(self, region: str, api_min_replicas: Optional[int] = None,
                  workers: Optional[int] = None) -> None:
        rc = self.config.regions[region]
        sets: list[str] = []
        if api_min_replicas is not None:
            sets.append(f"api.autoscaling.minReplicas={api_min_replicas}")
        if workers is not None:
            sets.append("workers.enabled=false" if workers == 0 else f"workers.enabled=true,workers.replicas={workers}")
        if not sets:
            return
        cmd = ["helm", "upgrade", rc.release, rc.chart, "--kube-context", rc.kube_context,
               "--namespace", rc.namespace, "--reuse-values", "--set", ",".join(sets),
               "--wait", "--timeout", "10m"]
        proc = self.run(cmd)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            if "Kubernetes cluster unreachable" in err or "i/o timeout" in err or "no such host" in err:
                raise Unreachable(f"{region}: {err[:200]}")
            raise RuntimeError(f"helm upgrade failed in {region}: {err[:300]}")


def build_aws_adapters(config: Config) -> Adapters:
    clients = _Clients()
    return Adapters(
        health=HttpHealth(config),
        db=AuroraGlobal(config, clients),
        workload=HelmWorkload(config),
        dns=Route53Failover(config, clients),
    )
