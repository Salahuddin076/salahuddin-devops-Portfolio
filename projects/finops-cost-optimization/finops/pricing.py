"""Illustrative price table.

ALL PRICES IN THIS MODULE ARE ILLUSTRATIVE, APPROXIMATE us-east-1 ON-DEMAND
LIST PRICES (Linux, shared tenancy). VERIFY AGAINST CURRENT AWS PRICING
(https://aws.amazon.com/pricing/) BEFORE USING ANY NUMBER FOR A REAL DECISION.

They exist so the synthetic generator and the rightsizing engine have
self-consistent numbers to work with. No real savings are claimed anywhere in
this project.
"""

from __future__ import annotations

from decimal import Decimal

HOURS_PER_MONTH = Decimal("730")

# Size order within a family, smallest first. Within the families modelled here
# each step up doubles vCPU and memory.
SIZE_ORDER: tuple[str, ...] = ("large", "xlarge", "2xlarge", "4xlarge")

# Illustrative, approximate us-east-1 on-demand list prices, USD per hour.
# Verify against current AWS pricing.
EC2_HOURLY: dict[str, Decimal] = {
    # General purpose, Intel x86_64
    "m5.large": Decimal("0.096"),
    "m5.xlarge": Decimal("0.192"),
    "m5.2xlarge": Decimal("0.384"),
    "m5.4xlarge": Decimal("0.768"),
    # Compute optimised, Intel x86_64
    "c5.large": Decimal("0.085"),
    "c5.xlarge": Decimal("0.170"),
    "c5.2xlarge": Decimal("0.340"),
    "c5.4xlarge": Decimal("0.680"),
    # Memory optimised, Intel x86_64
    "r5.large": Decimal("0.126"),
    "r5.xlarge": Decimal("0.252"),
    "r5.2xlarge": Decimal("0.504"),
    "r5.4xlarge": Decimal("1.008"),
    # Graviton3 (arm64) equivalents
    "m7g.large": Decimal("0.0816"),
    "m7g.xlarge": Decimal("0.1632"),
    "m7g.2xlarge": Decimal("0.3264"),
    "m7g.4xlarge": Decimal("0.6528"),
    "c7g.large": Decimal("0.0725"),
    "c7g.xlarge": Decimal("0.1450"),
    "c7g.2xlarge": Decimal("0.2900"),
    "c7g.4xlarge": Decimal("0.5800"),
    "r7g.large": Decimal("0.1071"),
    "r7g.xlarge": Decimal("0.2142"),
    "r7g.2xlarge": Decimal("0.4284"),
    "r7g.4xlarge": Decimal("0.8568"),
}

# x86 family -> Graviton family with the same vCPU:memory ratio.
GRAVITON_EQUIVALENT: dict[str, str] = {"m5": "m7g", "c5": "c7g", "r5": "r7g"}

# Illustrative, approximate us-east-1 prices for non-EC2 services used by the
# synthetic generator. Verify against current AWS pricing.
RDS_HOURLY: dict[str, Decimal] = {
    "db.r5.large": Decimal("0.250"),  # single-AZ; Multi-AZ is roughly 2x
    "db.m5.large": Decimal("0.171"),
}
EKS_CLUSTER_HOURLY = Decimal("0.10")
NAT_GATEWAY_HOURLY = Decimal("0.045")
NAT_GATEWAY_PER_GB = Decimal("0.045")
DATA_TRANSFER_OUT_PER_GB = Decimal("0.09")
DATA_TRANSFER_INTER_AZ_PER_GB = Decimal("0.02")  # $0.01/GB charged in each direction
S3_STANDARD_PER_GB_MONTH = Decimal("0.023")
EBS_PER_GB_MONTH: dict[str, Decimal] = {
    "gp3": Decimal("0.08"),
    "gp2": Decimal("0.10"),
}


def split_instance_type(instance_type: str) -> tuple[str, str]:
    """Return (family, size) for an EC2 instance type such as ``m5.2xlarge``."""
    family, sep, size = instance_type.strip().partition(".")
    if not sep or not family or not size:
        raise ValueError(f"not an EC2 instance type: {instance_type!r}")
    return family, size


def ec2_hourly(instance_type: str) -> Decimal | None:
    """Illustrative on-demand hourly price, or None when not in the table."""
    return EC2_HOURLY.get(instance_type.strip())


def ebs_gb_month(volume_type: str) -> Decimal | None:
    return EBS_PER_GB_MONTH.get(volume_type.strip().lower())
