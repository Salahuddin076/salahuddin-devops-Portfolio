# ADR 0001: Warm standby instead of active-active or pilot light

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-multi-region-eks-dr (reference implementation)

## Context

The order API runs on EKS in us-east-1 with Aurora PostgreSQL, Valkey and
S3. It has to survive the loss of the whole region with a recovery time
in minutes, not hours. It must also lose as little committed data as the
storage layer allows. AWS describes four multi-region strategies:
backup and restore, pilot light, warm standby, and multi-site
active-active. Backup and restore is covered by the sibling
[aws-backup-cross-region-dr](../../../aws-backup-cross-region-dr/) project.
Its recovery time is the time to rebuild a whole stack, and that is too
slow for this service.

The application is a typical OLTP service. Every write goes to one
PostgreSQL database, orders have to be strongly consistent (stock,
payments), and background workers process jobs that have side effects.

## Options

1. **Pilot light.** Data replicates to the DR region, but there is no
   compute there, or the EKS cluster has no workloads. Failover starts with
   provisioning nodes, pulling images and starting pods, and scaling up
   only begins after that.
2. **Warm standby (chosen).** The full stack runs in DR at a reduced size.
   The EKS cluster has a small node group, the API serves the health check
   and reads from the Aurora secondary, and the workers are scaled to 0.
   Failover means promoting the database, scaling up and moving DNS.
3. **Active-active.** Both regions serve traffic and take writes. That
   needs either a multi-writer data store (Aurora DSQL, DynamoDB global
   tables) or partitioning writes by key with conflict handling.

## Decision

Warm standby: the same Terraform module and the same Helm chart in both
regions. Only the size differs, plus `workers.enabled=false` in DR. Aurora
Global Database replicates storage into a secondary cluster that has one
instance, so promotion does not wait for an instance to be created.

## Consequences

Good:

- **Recovery is mostly scaling, not building.** The cluster, add-ons, Pod
  Identity, Load Balancer Controller, ALB, certificates and DNS health
  checks already exist and are already proven healthy by Route 53 every 30
  seconds. During failover the steps are the database promotion, the HPA
  minimum, the worker replica count and one DNS change.
- **The standby is tested all the time.** The DR API answers
  `/healthz/ready` against the replicated database and its own cache. A
  broken standby shows up as a failing health check on an ordinary
  Tuesday, not during the incident.
- **One writer, so no conflict resolution.** The application keeps
  PostgreSQL semantics. The hard part is making sure there is exactly one
  writer, and the failover orchestrator and
  [ADR 0005](0005-fencing-before-promotion.md) handle that.

Accepted costs:

- **Standby spend.** A second Aurora cluster with one instance, a second
  EKS control plane, two or more nodes, NAT, an idle ALB and cross-region
  transfer. [cost.md](../cost.md) estimates it at roughly 40-50% of the
  primary region's fixed cost (illustrative).
- **RPO is not zero in an unplanned failover.** Aurora Global Database
  replicates asynchronously. A regional loss loses whatever had not yet
  replicated, which is typically under a second of writes, but this
  project does not claim a figure. A planned switchover loses nothing.
- **Capacity during scale-up.** The DR node group has to grow from 2 nodes
  to production size when the HPA minimum rises. EC2 capacity in the DR
  region during a large regional event is not guaranteed. Mitigations:
  On-Demand Capacity Reservations for the minimum production footprint (at
  a cost), or accepting degraded throughput for the first minutes.

Not chosen, and when to revisit:

- **Active-active** if the business needs regional write availability
  measured in seconds, and the data model can move to a multi-writer
  store or partition writes by customer. That is an application redesign,
  not an infrastructure change.
- **Pilot light** if the standby cost becomes the main constraint and a
  recovery time of tens of minutes is acceptable. The same Terraform works
  with `node_scaling.min = 1` and the API scaled to 0. The orchestrator's
  scale step already raises everything.
