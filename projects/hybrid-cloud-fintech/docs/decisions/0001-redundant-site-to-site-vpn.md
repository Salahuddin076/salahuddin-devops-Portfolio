# 0001: Redundant Site-to-Site VPN instead of Direct Connect

## Status

Accepted (portfolio reference).

## Context

Hybrid payments platforms typically reach on-prem over AWS Direct Connect
(a dedicated circuit) with VPN as backup, or over VPN alone for smaller
footprints. Direct Connect needs a cross-connect at a physical colocation
facility and an agreement with a DX partner -- neither exists, or can
exist, for a validate-only portfolio project with no real on-prem site.

## Decision

Model connectivity with two independent, redundant Site-to-Site VPN
connections (`terraform/modules/connectivity`): two Customer Gateways
(representing two physically separate on-prem edge devices) and one VPN
Connection per gateway, giving 4 IPsec tunnels total. `terraform validate`
can fully exercise this without any colocation facility, cross-connect, or
DX partner account -- it is pure AWS + Terraform.

## Consequences

- This reference proves the *redundancy and segmentation* pattern, not DX's
  specific operational characteristics (lower jitter, no internet transit).
  A real production build at this scale would very likely add Direct
  Connect as the primary path and keep this VPN pair as the automatic
  failover, not the only path.
- The `on_prem_gateways` variable's two-gateway minimum (enforced by a
  variable `validation` block) is the one invariant this repo can test
  without a real circuit: a single customer gateway is a single point of
  failure for the hybrid link regardless of which connectivity technology
  sits behind it.
- `var.static_routes_only` defaults to `false` (BGP), matching how most
  on-prem routers in this kind of estate are actually configured; static
  routing is available for simpler on-prem devices that don't speak BGP.
