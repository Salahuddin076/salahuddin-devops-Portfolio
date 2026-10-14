"""Warm-standby failover orchestrator for the multi-region EKS DR reference.

`python3 -m failover status|plan|execute` (run with `src` on the path). The
orchestrator depends only on four small ports (health, database, workload,
DNS). Tests inject fakes; the real adapters in `failover.aws` import boto3
lazily and shell out to helm/kubectl, so this package imports with the
standard library alone.
"""

__version__ = "0.1.0"
