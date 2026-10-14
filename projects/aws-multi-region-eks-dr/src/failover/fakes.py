"""An in-memory two-region world implementing all four ports.

Used by the tests and by `--adapters fake`, which is how the README and
runbook output was produced. The world can be saved to and loaded from a
JSON file (`--fake-world`), so `execute` followed by `status` shows the
result, which makes the CLI usable for game-day rehearsals with no cloud.

It reproduces what the orchestrator relies on, not the AWS APIs:
- an unreachable region fails every workload call and reports unreachable;
- the global cluster's metadata keeps naming a dead primary as writer
  (that's what the real control plane shows during a regional outage);
- detaching a secondary leaves two writers until the old one is rebuilt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from failover.ports import GlobalCluster, Health, Scale, Unreachable

SCENARIOS = ("healthy", "primary-down", "lagging", "split-brain")


@dataclass
class RegionSim:
    reachable: bool = True
    healthy: bool = True
    api_min_replicas: int = 3
    workers: int = 0


@dataclass
class FakeCloud:
    regions: dict[str, RegionSim]
    members: list[str]
    writer: Optional[str]
    detached: list[str] = field(default_factory=list)
    lag: dict[str, Optional[float]] = field(default_factory=dict)
    dns_primary: Optional[str] = None
    # method name -> number of upcoming calls that raise (crash simulation)
    fail_next: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    # -- construction ---------------------------------------------------------

    @classmethod
    def scenario(cls, name: str, primary: str = "us-east-1", dr: str = "us-west-2") -> "FakeCloud":
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}; choose from {', '.join(SCENARIOS)}")
        world = cls(
            regions={
                primary: RegionSim(api_min_replicas=3, workers=2),
                dr: RegionSim(api_min_replicas=2, workers=0),
            },
            members=[primary, dr],
            writer=primary,
            lag={dr: 0.4},
            dns_primary=primary,
        )
        if name == "primary-down":
            world.regions[primary].reachable = False
            world.regions[primary].healthy = False
            world.lag[dr] = 1.2  # last datapoint before the outage
        elif name == "lagging":
            world.lag[dr] = 42.0
        elif name == "split-brain":
            # The DR cluster was detached and promoted by hand while the
            # primary kept running: two writers, nothing fenced.
            world.members = [primary]
            world.detached = [dr]
        return world

    # -- persistence (for --fake-world) ---------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "regions": {r: vars(s).copy() for r, s in self.regions.items()},
            "members": list(self.members),
            "writer": self.writer,
            "detached": list(self.detached),
            "lag": dict(self.lag),
            "dns_primary": self.dns_primary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FakeCloud":
        return cls(
            regions={r: RegionSim(**s) for r, s in data["regions"].items()},
            members=list(data["members"]),
            writer=data["writer"],
            detached=list(data.get("detached", [])),
            lag=dict(data.get("lag", {})),
            dns_primary=data.get("dns_primary"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "FakeCloud":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    # -- helpers --------------------------------------------------------------

    def _record(self, method: str, *args: Any) -> None:
        self.calls.append((method, args))
        remaining = self.fail_next.get(method, 0)
        if remaining:
            self.fail_next[method] = remaining - 1
            raise RuntimeError(f"injected failure in {method}")

    def _region(self, region: str) -> RegionSim:
        if region not in self.regions:
            raise KeyError(f"unknown region {region}")
        return self.regions[region]

    def mutating_calls(self) -> list[tuple[str, tuple[Any, ...]]]:
        return [c for c in self.calls if c[0] in ("set_scale", "switchover", "detach_and_promote", "set_active")]

    def rebuild_as_secondary(self, region: str) -> None:
        """Simulate the failback runbook's rebuild: the old primary's cluster is
        deleted and re-added as a secondary of the current writer."""
        writer = next(r for r in self.writers() if r != region)
        self.detached = []
        self.members = [writer, region]
        self.writer = writer
        self.lag[region] = 0.5
        self.regions[region].reachable = True
        self.regions[region].healthy = True

    # -- HealthPort -----------------------------------------------------------

    def check(self, region: str) -> Health:
        self._record("check", region)
        sim = self._region(region)
        if not sim.reachable:
            return Health(False, False, "connect timeout")
        if not sim.healthy:
            return Health(True, False, "HTTP 503 from /healthz/ready")
        return Health(True, True, "HTTP 200 from /healthz/ready")

    # -- DatabasePort ---------------------------------------------------------

    def global_cluster(self) -> GlobalCluster:
        self._record("global_cluster")
        return GlobalCluster(self.writer if self.members else None, tuple(self.members))

    def writers(self) -> list[str]:
        self._record("writers")
        out = [self.writer] if self.writer and self.members else []
        return out + [r for r in self.detached if r not in out]

    def replication_lag_seconds(self, region: str) -> Optional[float]:
        self._record("replication_lag_seconds", region)
        if region == self.writer or region not in self.members:
            return None
        return self.lag.get(region)

    def switchover(self, target_region: str) -> None:
        self._record("switchover", target_region)
        if target_region not in self.members:
            raise RuntimeError(f"{target_region} is not a member of the global cluster")
        if not self._region(self.writer).reachable:
            raise RuntimeError("switchover needs the current writer region to be available")
        old = self.writer
        self.writer = target_region
        self.lag.pop(target_region, None)
        self.lag[old] = 0.0

    def detach_and_promote(self, target_region: str) -> None:
        self._record("detach_and_promote", target_region)
        if target_region not in self.members:
            raise RuntimeError(f"{target_region} is not a member of the global cluster")
        self.members.remove(target_region)
        self.detached.append(target_region)
        self.lag.pop(target_region, None)

    # -- WorkloadPort ---------------------------------------------------------

    def get_scale(self, region: str) -> Scale:
        self._record("get_scale", region)
        sim = self._region(region)
        if not sim.reachable:
            raise Unreachable(f"{region}: EKS API endpoint timed out")
        return Scale(sim.api_min_replicas, sim.workers)

    def set_scale(self, region: str, api_min_replicas: Optional[int] = None,
                  workers: Optional[int] = None) -> None:
        sim = self._region(region)
        if not sim.reachable:
            self.calls.append(("set_scale", (region, api_min_replicas, workers)))
            raise Unreachable(f"{region}: EKS API endpoint timed out")
        self._record("set_scale", region, api_min_replicas, workers)
        if api_min_replicas is not None:
            sim.api_min_replicas = api_min_replicas
        if workers is not None:
            sim.workers = workers

    # -- DnsPort --------------------------------------------------------------

    def active_region(self) -> Optional[str]:
        self._record("active_region")
        return self.dns_primary

    def set_active(self, region: str) -> None:
        self._record("set_active", region)
        self._region(region)
        self.dns_primary = region
