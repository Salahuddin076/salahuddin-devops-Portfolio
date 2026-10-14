# ADR 0002: A standard-library policy checker here, Checkov or OPA/Conftest in a real organisation

- **Status:** Accepted (for this repository)
- **Date:** 2026-10-14
- **Context:** cloud-security-waf-automation (portfolio implementation)

## Context

Pull requests that change infrastructure need an automated gate for a known
set of dangerous misconfigurations: public buckets, world-open SSH and RDP,
admin IAM policies, unencrypted databases, CloudTrail without integrity
validation, and public load balancers without a WAF. The gate must:

- evaluate the **plan**, not just the source, so module inputs, defaults and
  `for_each` expansions are resolved;
- support **time-boxed, owned exceptions**;
- emit **SARIF** so findings show up in GitHub code scanning;
- run in CI on a stock runner.

The established tools for this:

| Tool | Model | Strengths | Costs |
|---|---|---|---|
| **Checkov** | Python, ~1,000 built-in checks across Terraform, CloudFormation, Kubernetes and more; scans source or plan JSON | Broad coverage on day one, SARIF output, inline `#checkov:skip` comments, custom checks in Python or YAML | A large dependency tree. Built-in checks need tuning. Skips can be added without an expiry |
| **OPA / Conftest** | Rego policies over plan JSON | General-purpose policy engine also used for Kubernetes admission and API authorisation. Policies are data, testable with `opa test` | Rego has a learning curve. You write every rule yourself. Exceptions are whatever you build |
| **tfsec / Trivy config** | Go binary, built-in checks | Fast, single binary | Similar trade-offs to Checkov |
| **HashiCorp Sentinel** | Policy language in Terraform Cloud and Enterprise | Native enforcement levels (advisory, soft and hard mandatory) | Needs those products |

## Decision

For **this portfolio repository**, write the checker in standard-library
Python (`policy/check_plan.py`, under 600 lines including SARIF output and
exceptions). It's dependency-free: no `pip install`, no supply-chain
surface, and it runs on any machine with Python 3.

The main reason is to **show the rule logic** instead of hiding it behind a
tool. Each rule is a short, readable function, with tests for passing and
failing cases. The non-obvious parts are explicit: linking a public access
block to its bucket when the bucket ID is unknown at plan time, and
following a module input variable back to the ALB it protects.

**In a real organisation I would most likely not do this.** I'd adopt
**Checkov** for breadth, and add **OPA/Conftest** if the organisation
already uses Rego elsewhere (for Kubernetes admission, say), so there's one
policy language. The custom work would be what the tools don't give you
out of the box: an exceptions process with owners and expiry dates, and
routing of SARIF results. [checkov.md](../checkov.md) shows the equivalent
Checkov run against this project's Terraform.

## Consequences

Good:

- **Zero dependencies**: nothing to pin, scan or update, and it runs in a
  locked-down CI.
- **Every line is reviewable**, which suits an interview and a security
  review.
- **Exceptions are first-class**: owner, reason, mandatory expiry, exact
  matching, expired entries reported. In Checkov that needs either
  discipline or a wrapper.
- **The SARIF output is exactly what code scanning needs**, including
  suppressed results for exceptions.

Accepted costs:

- **Six rules against Checkov's hundreds.** Coverage is the main thing
  this gives up, and it's the reason a real team should use a maintained
  tool.
- **Maintenance falls on us**: new resource types (for example
  `aws_vpc_security_group_ingress_rule` replacing inline rules), provider
  schema changes and plan-format changes.
- **Plan JSON quirks** (unknown values, references, module nesting) are
  handled for the cases tested, not exhaustively.

## Migration path

If this were adopted for real, the rules map onto existing Checkov checks
(public access block, open SSH and RDP, `*:*` IAM, RDS encryption,
CloudTrail validation, ALB with WAF). The exceptions file could become
Checkov skips generated with their expiry tracked by this script, or the
SARIF from both tools could be uploaded side by side under different
categories. The test fixtures stay useful as regression cases for either
tool.
