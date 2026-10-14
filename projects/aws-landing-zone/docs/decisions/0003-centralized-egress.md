# ADR 0003: Centralized internet egress through the Transit Gateway hub

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-landing-zone (reference implementation of a pattern used in production work; synthetic values)

## Context

Spoke VPCs in workload accounts need outbound internet access (package
repositories, partner APIs, SaaS). The two common patterns:

1. **NAT gateways in every VPC**: an IGW and NAT per AZ in every spoke.
2. **Centralized egress**: spokes have no IGW. A default route sends traffic
   through the Transit Gateway to an egress VPC in a shared account, which
   holds the NAT gateways.

We also want prod and nonprod isolated from each other, a small number of
stable egress IPs for partner allow-lists, and one place to add inspection
later.

## Decision

Centralize egress in the shared-services account:

- an egress VPC with a NAT gateway per AZ (`single_nat_gateway` for a
  cheaper, less resilient option), associated with the shared TGW route
  table;
- spokes with private subnets only and `0.0.0.0/0 → TGW`;
- `0.0.0.0/0 → egress attachment` in every TGW route table, **and**
  blackhole routes for the RFC 1918 supernets in every table, so the
  default route can't be used to hairpin between environments through the
  egress VPC;
- appliance mode on the egress attachment, so both directions of a flow use
  the same AZ.

## Consequences

Good:

- **No IGW in any workload account.** A misconfigured security group can't
  expose an instance to the internet when there's no route from it.
- **Stable egress IPs**: two Elastic IPs for the whole organization, which
  partners can allow-list.
- **Cheaper NAT hours with more than a few spokes**: ~$66/month for two
  hub NAT gateways against ~$330/month for five spokes × two AZs
  ([cost](../cost.md), illustrative).
- **One insertion point** for AWS Network Firewall or a proxy later,
  between the TGW subnets and the NAT.

Accepted costs:

- **TGW processing on every byte** (~$0.02/GB) on top of NAT processing.
  Heavy egress spokes pay more than they would with local NAT.
- **Blast radius.** The hub is a shared dependency. If an AZ's NAT fails,
  every spoke in that AZ loses egress (mitigated by a NAT per AZ, and lost
  entirely with `single_nat_gateway`).
- **Routing subtlety.** Without the blackholes, isolation silently breaks.
  The static tests pin the propagation matrix and the blackhole routes for
  that reason.
- **Throughput limits** are shared: per-attachment and per-NAT bandwidth
  limits apply to the sum of all spokes in an AZ.

## Alternatives considered

- **NAT per spoke.** Simpler routing and no shared dependency. Better for
  very few spokes or one huge egress consumer, and still the right call for
  sandbox accounts that don't attach to the hub at all.
- **Egress through a proxy fleet only** (no NAT). Stronger control and
  logging per URL, but an operational burden. It can be layered on later
  through the same insertion point.
- **IPv6 with egress-only internet gateways.** Removes NAT cost for IPv6
  destinations. Worth revisiting when enough dependencies support IPv6.
