# ADR 0001: OUs follow policy boundaries, not the org chart

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-landing-zone (reference implementation of a pattern used in production work; synthetic values)

## Context

An OU is the unit SCPs and tag policies attach to. An account inherits
everything above it and can only be in one place. The first OU design that
comes to mind usually mirrors the company: an OU per department, per
product, per team. That breaks down quickly:

- Teams reorganize every year, and moving accounts between OUs changes
  their guardrails as a side effect.
- Two teams with identical requirements need the same SCPs attached twice,
  and both copies count against the 5-per-target limit.
- A team OU with both prod and dev accounts can't apply a prod-only
  guardrail without per-account SCPs, which don't scale and are easy to
  forget.

## Decision

Cut OUs where the **set of guardrails** differs, and nowhere else:

| OU | What makes it different |
|---|---|
| Security | Holds the log archive and security tooling. Nobody else operates these accounts. Strictest access |
| Infrastructure | Shared services and the network hub. Platform team operates it. Runs EC2 |
| Workloads → Prod / NonProd | Shared workload guardrails at Workloads (root deny, tags required on create). Prod and NonProd differ in access and network, and get room for environment-specific SCPs |
| Sandbox | Experiments: no tag requirement, no hub access, budget alerts, region allow-list still applies |
| Suspended | Deny-all. Decommissioning or quarantine is one move, not a policy edit |

Ownership (team, product, cost center) lives in **tags** (enforced by the
tag policy and the require-tags SCP) and in **Identity Center groups**, not
in the OU tree.

## Consequences

Good:

- **Re-orgs don't touch guardrails.** A team change is a tag and
  group-assignment change.
- **Room under the limits.** The deepest path (root → workloads → prod) uses
  4 + 4 + 2 attachment slots, and the root keeps one free for an emergency
  deny.
- **Reasoning is local.** `simulate_scp.py --ou prod` lists exactly the
  policies that apply, by level.

Accepted costs:

- **Per-team SCP differences need a new OU** (for example a PCI OU under
  Prod). That's a deliberate, reviewed change, which is the point.
- **Billing views by team come from tags**, so tag compliance matters. The
  require-tags SCP enforces it at creation for EC2 and RDS only.
- **Prod and NonProd share an OU parent**, so a mistake at Workloads hits
  both. Changes roll out Sandbox → NonProd → Workloads
  ([operations](../operations.md#changing-an-scp-safely)).

## Alternatives considered

- **OU per team.** Rejected for the reasons above.
- **Flat: everything under root, per-account SCPs.** Simple at five
  accounts, unmanageable at fifty, and every account hits the per-target
  limit separately.
- **Environment at the top (Prod OU, NonProd OU, each with Security,
  Workloads and so on inside).** It works, but duplicates the security and
  infrastructure OUs per environment, and the log archive is inherently
  cross-environment.
