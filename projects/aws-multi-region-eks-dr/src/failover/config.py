"""Failover configuration: which regions, which global cluster, what "active" means.

Most values come from the global environment's `failover_config` Terraform
output; the Kubernetes and scale settings are added by hand. See
config/failover.example.json.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REGION_RE = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-[0-9]$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RegionConfig:
    name: str
    cluster_id: str
    cluster_arn: str
    health_url: str
    health_check_id: Optional[str]
    kube_context: str
    namespace: str
    release: str
    chart: str
    active_api_min_replicas: int
    active_workers: int


@dataclass(frozen=True)
class Config:
    app: str
    global_cluster_id: str
    primary_region: str
    dr_region: str
    max_replication_lag_seconds: float
    hosted_zone_id: Optional[str]
    record_name: Optional[str]
    regions: dict[str, RegionConfig]

    def other(self, region: str) -> str:
        if region == self.primary_region:
            return self.dr_region
        if region == self.dr_region:
            return self.primary_region
        raise ConfigError(f"{region} is not one of the configured regions ({self.primary_region}, {self.dr_region})")


def _req(data: dict[str, Any], key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ConfigError(f"{where}: missing required key {key!r}")
    return data[key]


def _positive_int(value: Any, where: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"{where}: must be an integer >= {minimum}, got {value!r}")
    return value


def parse_config(data: dict[str, Any]) -> Config:
    primary = _req(data, "primary_region", "config")
    dr = _req(data, "dr_region", "config")
    for r in (primary, dr):
        if not REGION_RE.match(r):
            raise ConfigError(f"config: {r!r} is not a region name")
    if primary == dr:
        raise ConfigError("config: primary_region and dr_region must differ")
    lag = data.get("max_replication_lag_seconds", 5)
    if not isinstance(lag, (int, float)) or isinstance(lag, bool) or lag <= 0:
        raise ConfigError("config: max_replication_lag_seconds must be a positive number")

    raw_regions = _req(data, "regions", "config")
    if set(raw_regions) != {primary, dr}:
        raise ConfigError(f"config: regions must have exactly {primary} and {dr}, got {sorted(raw_regions)}")
    regions: dict[str, RegionConfig] = {}
    for name, r in raw_regions.items():
        where = f"config.regions.{name}"
        active = _req(r, "active_scale", where)
        regions[name] = RegionConfig(
            name=name,
            cluster_id=_req(r, "cluster_id", where),
            cluster_arn=_req(r, "cluster_arn", where),
            health_url=_req(r, "health_url", where),
            health_check_id=r.get("health_check_id"),
            kube_context=_req(r, "kube_context", where),
            namespace=r.get("namespace", "orders"),
            release=r.get("release", "dr-app"),
            chart=r.get("chart", "helm/dr-app"),
            active_api_min_replicas=_positive_int(active.get("api_min_replicas"), f"{where}.active_scale.api_min_replicas", 1),
            active_workers=_positive_int(active.get("workers"), f"{where}.active_scale.workers", 1),
        )
    return Config(
        app=data.get("app", "dr-app"),
        global_cluster_id=_req(data, "global_cluster_id", "config"),
        primary_region=primary,
        dr_region=dr,
        max_replication_lag_seconds=float(lag),
        hosted_zone_id=data.get("hosted_zone_id"),
        record_name=data.get("record_name"),
        regions=regions,
    )


def load_config(path: Path) -> Config:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    return parse_config(data)
