"""The four ports the orchestrator talks to, and the errors they may raise.

Keep these small: each method is one question or one action, so a fake can
reproduce it exactly and a real adapter maps it to one or two API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class Unreachable(Exception):
    """The region (or its cluster API) can't be reached right now."""


@dataclass(frozen=True)
class Health:
    reachable: bool
    healthy: bool
    detail: str


@dataclass(frozen=True)
class Scale:
    api_min_replicas: int
    workers: int


@dataclass(frozen=True)
class GlobalCluster:
    """What the Aurora global cluster says about its members.

    writer_region: the member that is the global writer (None if no members).
    members: regions still attached to the global cluster.
    """

    writer_region: Optional[str]
    members: tuple[str, ...]


class HealthPort(Protocol):
    def check(self, region: str) -> Health:
        """Deep health of the region's public entry point (/healthz/ready)."""


class DatabasePort(Protocol):
    def global_cluster(self) -> GlobalCluster: ...

    def writers(self) -> list[str]:
        """Regions whose cluster accepts writes right now: the global writer
        plus any detached (standalone) cluster. More than one unfenced
        writer is a split brain."""

    def replication_lag_seconds(self, region: str) -> Optional[float]:
        """Latest replication lag into a secondary region, None if unknown."""

    def switchover(self, target_region: str) -> None:
        """Planned: managed switchover (failover-global-cluster --switchover).
        Returns once the target is the global writer."""

    def detach_and_promote(self, target_region: str) -> None:
        """Unplanned: remove-from-global-cluster on the target, then wait until
        it is a standalone writer."""


class WorkloadPort(Protocol):
    def get_scale(self, region: str) -> Scale:
        """Raise Unreachable if the region's cluster API can't be reached."""

    def set_scale(self, region: str, api_min_replicas: Optional[int] = None,
                  workers: Optional[int] = None) -> None:
        """Change HPA minReplicas and/or worker replicas (None = unchanged).
        Raise Unreachable if the cluster API can't be reached."""


class DnsPort(Protocol):
    def active_region(self) -> Optional[str]:
        """Region whose failover record is PRIMARY (None before phase 2)."""

    def set_active(self, region: str) -> None:
        """Make `region` PRIMARY and the other SECONDARY in one change batch."""


@dataclass
class Adapters:
    health: HealthPort
    db: DatabasePort
    workload: WorkloadPort
    dns: DnsPort
