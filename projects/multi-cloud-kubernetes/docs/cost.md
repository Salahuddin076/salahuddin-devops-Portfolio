# Cost (illustrative)

Figures below are illustrative public list-price structure as of writing,
not a quote, and not sourced to a specific invoice -- see
`docs/comparison.yaml`'s `control_plane_pricing` dimension for the
underlying claims.

| Cloud | Control plane | Notes |
|---|---|---|
| EKS | Flat hourly fee per cluster (~$0.10/hr) | Plus one Fargate/EC2 node fee per worker; no free tier |
| AKS | Free (default tier) | Paid Standard/Premium tiers add an SLA and a longer support window |
| GKE | One free zonal cluster per billing account | Autopilot and additional/regional clusters bill a flat per-hour management fee |

Running the same reference workload (3 replicas, 100m/128Mi requests) on all
three clouds at once, purely to keep this comparison honest, would cost
roughly 3x one cloud's node cost plus each cloud's own control-plane fee --
there is no cost benefit to multi-cloud here, only a resilience-against-a
-single-vendor argument, which is explicitly not what this project claims
(see `docs/decisions/0002-identity-bound-not-abstracted.md`: this is a
reference comparison, not a failover design, so it is never run on all three
clouds simultaneously for real traffic).

The actual cost lesson this project demonstrates: the Terraform in
`terraform/modules/identity-bindings` creates only IAM-layer objects (an IAM
role, a managed identity, a service account) -- none of which carry a
runtime cost on any of the three clouds. The cost of "being multi-cloud" here
is engineering time (maintaining three ingress/storage overlays and reading
three clouds' upgrade policies), not infrastructure spend.
