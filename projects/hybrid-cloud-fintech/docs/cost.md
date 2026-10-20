# Cost

> **Illustrative and approximate.** us-east-1 list prices as understood at
> the time of writing, rounded, before free tiers and discounts. Not
> quotes. Nothing in this project has been deployed or billed. The EKS and
> RDS costs this hybrid design would actually run on top of are covered by
> `../aws-multi-region-eks-dr` and `../aws-landing-zone`'s cost docs, not
> repeated here -- this file is only the connectivity/segmentation layer's
> own cost.

## What drives the bill

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| VPN connection-hours | ~$0.05/hour per VPN connection, billed whether traffic flows or not | This design's 2 connections (4 tunnels) cost ~$73/month combined just to exist, before any data moves -- the redundancy in [ADR 0001](decisions/0001-redundant-site-to-site-vpn.md) has a fixed monthly cost, not just an operational one |
| VPN data processing | ~$0.09/GB processed through the VPN endpoint | Dominant cost at real replication volumes; a database replication stream running 24x7 at even a modest rate adds up fast -- this is the main argument for Direct Connect once volume justifies the colocation cost |
| Virtual Private Gateway | No separate hourly charge beyond the VPN connections it terminates | |
| Security groups, NACLs | No charge | The segmentation module itself is free; the cost is entirely in the connectivity module |
| CloudWatch (VPN tunnel state alarms, not built here but implied by docs/operations.md's "both tunnels down" check) | ~$0.10/alarm | Add these before relying on the redundancy -- an unmonitored redundant tunnel that's actually down defeats the point |

## Example: this project's reference topology, if it were real

Assumptions: 2 VPN connections (4 tunnels) running 24x7, ~50 GB/day of
database replication traffic (small-to-medium transactional estate), no
Direct Connect.

| Item | Monthly (approx.) |
|---|---|
| 2 VPN connections, 24x7 (~1,460 connection-hours total) | ~$73 |
| Data processing, ~1.5 TB/month replication traffic | ~$135 |
| Tunnel-state alarms (8: 2 per tunnel x 4 tunnels) | ~$1 |
| **Total (connectivity layer only)** | **roughly $205-215/month** |

For comparison, a single Direct Connect circuit (1 Gbps, dedicated) runs
roughly $0.30/hour port-hours (~$220/month) plus data transfer at a lower
per-GB rate than VPN and a one-time colocation/cross-connect cost that
varies by facility -- which is why [ADR 0001](decisions/0001-redundant-site-to-site-vpn.md)
frames VPN as the backup path once volume justifies DX, not a permanent
choice at scale. At the ~1.5 TB/month in the example above, the two options
are cost-comparable; DX starts winning clearly past a few TB/month, which
is also typically where the jitter/latency argument for DX becomes
operationally material too, not just financial.

## What's genuinely free in this project

- `terraform/modules/segmentation`: security groups and NACLs carry no
  AWS charge.
- `ansible/`: the baseline role and playbook cost nothing to run beyond
  the compute the hosts already incur.
- `src/degrade/`: pure application code; `FileOutbox` uses local disk
  already provisioned for the instance it runs on.
