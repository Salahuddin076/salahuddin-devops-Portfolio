# ADR 0004: Three Terraform roots (primary, dr, global) over one root with aliases

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-multi-region-eks-dr (reference implementation)

## Context

The infrastructure has two kinds of resources:

- **Regional stacks**: VPC, EKS, node group, Valkey, KMS and the Pod
  Identity roles. These are identical except for size, and each one
  belongs to exactly one region.
- **Cross-region resources**: the Aurora Global Database, which spans
  both regions; S3 replication, which needs both buckets and one role;
  the replicated secret; and Route 53, a global service whose records
  point at both regions.

The simplest layout is one root module with two aliased providers that
creates everything in one state. The question is what happens to that
layout during the incident it exists for.

## Decision

Three roots, each with its own state:

```text
terraform/environments/primary  -> modules/regional-stack   (provider: us-east-1)
terraform/environments/dr       -> modules/regional-stack   (provider: us-west-2)
terraform/environments/global   -> modules/global-data      (providers: aws.primary, aws.dr)
```

- `regional-stack` uses the default provider and is called once per
  region. It validates directly.
- `global-data` declares `configuration_aliases = [aws.primary, aws.dr]`,
  so it can only be validated through a caller. It has a minimal
  [`validation-harness`](../../terraform/modules/global-data/validation-harness)
  (region-only providers, placeholder inputs) as well as
  `environments/global`. The harness sets the phase-2 DNS inputs so the
  Route 53 resources are type-checked too.
- Values pass between roots as variables: the `global_data_inputs` output
  of each regional root becomes the `primary` / `dr` input of the global
  root. In real use, read them with `terraform_remote_state` or SSM
  parameters. Variables keep validation self-contained here.

## Why not a single root

- **Blast radius during an outage.** With one state, a plan refreshes
  every resource in both regions. While us-east-1 is impaired, the refresh
  of the us-east-1 half fails or hangs, and so does any change to the DR
  half, such as raising the DR node group's max size, which is exactly the
  change you want to make at that moment. With separate roots,
  `environments/dr` plans and applies without touching us-east-1.
- **State location.** Each regional state should be stored in its own
  region (a bucket in us-west-2 for the DR state). With one state there is
  one bucket, and it is in one of the two regions.
- **Change cadence and review.** Node group sizes and add-on versions
  change often and per region. The global data layer changes rarely and
  carefully, because a mistake there touches the database of record.
  Separate roots give separate plans, reviewers and pipelines.

## Consequences

- **Ordering.** Apply primary and dr (in either order or in parallel),
  then global, then install the chart in both regions, then apply global
  again with the ALB names (two-phase bootstrap, see
  [operations.md](../operations.md)).
- **Some names are agreed rather than referenced.** The app role's
  permissions name the bucket and secret that global-data creates
  (`app_bucket_name`, `app_secret_name`) before they exist. The defaults
  match on both sides, and a typo shows up as an `AccessDenied` in the
  app, not as a plan error. The alternative, global-data attaching
  policies to role names it receives, couples the roots in the other
  direction.
- **The global root still spans both regions.** That is unavoidable for
  an Aurora Global Database. After an unplanned failover it has known
  drift ([ADR 0002](0002-managed-switchover-vs-detach-promote.md)), and
  `ignore_changes` keeps a routine apply from undoing the failover (the
  DR cluster's `global_cluster_identifier`, the failover record roles).
- **Two copies of the regional root.** `environments/primary` and
  `environments/dr` differ only in variable defaults (CIDR, NAT mode, node
  sizes, cache size). A workspace-per-region layout would remove the
  copy, but each directory then needs the right workspace selected, and
  during an incident a wrong workspace is easy to pick. Two directories
  are hard to mix up.
