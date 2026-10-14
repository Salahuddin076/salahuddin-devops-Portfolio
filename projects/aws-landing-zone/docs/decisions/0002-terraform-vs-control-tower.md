# ADR 0002: Build on Organizations primitives in Terraform, not Control Tower

- **Status:** Accepted for this repository; see "When to choose differently"
- **Date:** 2026-10-14
- **Context:** aws-landing-zone (reference implementation of a pattern used in production work; synthetic values)

## Context

AWS Control Tower sets up a landing zone for you: the organization, a
Security OU with log-archive and audit accounts, an org trail, Config,
Identity Center, preventive and detective controls (SCPs and Config rules),
and Account Factory. Account Factory for Terraform (AFT) adds a GitOps
pipeline for vending and customizing accounts. Control Tower is maintained
by AWS, upgrades its baseline, and its controls are documented and tested.

This repository is a portfolio piece whose purpose is to show the
underlying primitives: Organizations, SCPs, the org trail, the bucket and
key policies, Identity Center and the Transit Gateway routing. You need to
understand those in either model, and you work with them directly when
Control Tower's defaults don't fit.

## Decision

Build directly on the primitives in Terraform: `aws_organizations_*`,
`aws_cloudtrail`, `aws_ssoadmin_*` and so on. SCPs are plain JSON files,
checked and simulated in CI.

## Honest comparison

| | Control Tower (+ AFT) | Primitives in Terraform (this repo) |
|---|---|---|
| Time to a working baseline | Hours | Days to weeks |
| Maintenance of the baseline | AWS (landing zone version upgrades) | You |
| Controls | Large managed library (preventive, detective, proactive), versioned by AWS | Exactly the SCPs you write, and nothing else |
| Visibility | Some resources are Control Tower-managed and drift-checked; editing them directly causes drift | Everything is in your code |
| SCP slots | Control Tower uses some of the 5 per OU for its own controls | All yours |
| OU and account structure | Must follow its conventions (Security OU, specific shared accounts), with nesting supported | Any structure |
| Network | Not included (AFT customizations or separate code) | Included |
| Region deny | A built-in control | Your own SCP, with your own exemptions |

## When to choose differently

**Control Tower with AFT is the right answer for most organizations**,
especially:

- teams without a dedicated platform group to own an org-level codebase;
- new organizations that want a supported baseline quickly;
- regulated environments that benefit from AWS-maintained, documented
  controls and their mapping to frameworks.

The primitives approach fits when:

- an existing organization predates Control Tower and its structure
  conflicts with Control Tower's conventions;
- the SCP slot budget is tight because of many custom guardrails;
- the platform team needs every resource in one reviewed codebase and
  already runs Terraform at org scope;
- or, as here, the goal is to show and understand the mechanics.

A common middle path is Control Tower for the baseline, with custom SCPs,
the network hub and the account baseline (budgets, Access Analyzer) as
Terraform alongside it. Most of this repository's modules work unchanged
in that model, except `organization` and `log-archive`, which Control Tower
replaces.

## Consequences

- We own upgrades: new AWS services in the region allow-list exemptions,
  new security services to protect, provider changes.
- Every guardrail needs its own tests. `check_scps.py` and the simulator
  tests exist because there's no managed control library behind this.
- Bootstrap is manual and staged ([operations](../operations.md#bootstrap-order)),
  where Control Tower automates it.
