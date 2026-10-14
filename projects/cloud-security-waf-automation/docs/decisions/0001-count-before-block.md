# ADR 0001: New WAF rules start in count mode and are flipped to block from log evidence

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** cloud-security-waf-automation (portfolio implementation)

## Context

A WAF rule that blocks legitimate traffic is an outage, and an outage the
WAF caused, not an attacker. AWS managed rule groups are generic. They know
nothing about this application, and some of their rules regularly misfire
on normal behaviour:

- `SizeRestrictions_BODY` (CommonRuleSet) blocks bodies over 8 KB, which
  includes most file uploads and large JSON documents.
- `SQLi_BODY` matches report builders, search syntax and admin tools that
  legitimately send SQL-looking text.
- `NoUserAgent_HEADER` blocks health checkers and some internal clients.

The rate rule has the same problem from the other direction. The right
limit depends on real per-client traffic, and a guess blocks a busy NAT
gateway full of real users.

We need a way to add protection without betting availability on a guess.

## Decision

1. **Every rule has a mode, `count` or `block`,** exposed as a Terraform
   variable: per managed group (`managed_rule_groups[*].mode`), and for the
   block list and the rate rule. For managed groups, count is
   `override_action { count {} }` and block is `override_action { none {} }`.
2. **New rules start in `count`.** The module defaults new optional groups
   (SQLi) and the rate rule to count.
3. **A rule is flipped to `block` only after reviewing at least one full
   business cycle of logs** (one week by default) with
   `scripts/waf_log_summary.py`. Its flip-to-block view lists, per
   count-mode rule, the requests it would *newly* block, the number of
   distinct clients and the dominant URI.
4. **False positives are handled at the narrowest level**: fix the
   request, scope down by path, or override the one rule to count
   (`rules_to_count`). The whole group goes back to count only in an
   emergency.
5. **The flip is a one-line, reviewed change** in a PR, and the revert is
   the same line. The blocked-requests alarm watches the first hour.

## Consequences

Good:

- **New protection doesn't cause outages.** The worst case for a
  count-mode rule is a missed attack that the rule wasn't stopping before
  it existed either.
- **Decisions have evidence.** "Would newly block 5 requests from 5
  clients, all on `/api/reports/query`" is a concrete reason not to flip
  yet. "The vendor says it's safe" isn't.
- **Exclusions stay visible.** An overridden rule keeps logging as COUNT,
  so the summary keeps reporting it and nobody forgets the exclusion
  exists.
- **Cheap rollback.** Count and block are the same rule. No deletion, no
  priority change, no lost metrics history.

Accepted costs:

- **Protection is delayed** by the observation window. For an actively
  exploited vulnerability, skip the window: deploy the specific rule in
  block mode directly, scoped as tightly as possible, and accept the risk
  deliberately.
- **Count mode costs the same as block mode** (same WCUs, same per-request
  charge) and adds log volume.
- **The summary hint is a heuristic.** "Many clients on one path" is
  usually a false positive, but a distributed attack on one endpoint looks
  the same. Someone still has to read sampled requests.
- **Ordering caveat.** A count-mode rule only sees what earlier rules let
  through, so it has to sit at its final priority during observation.

## Alternatives considered

- **Block from day one, fix complaints.** That's common, and it turns
  customers into the false-positive detector. Rejected.
- **Test in a staging environment only.** Staging doesn't have production
  traffic: no real browsers, no partner integrations, no month-end batch
  jobs. Useful for syntax, useless for false-positive rates.
- **Labels plus a separate blocking rule** (managed rule groups add labels
  such as `awswaf:managed:aws:sql-database:SQLi_Body`, and a later custom
  rule blocks on chosen labels). That's more precise, and the natural next
  step for complex exclusions. It's more rules and more WCUs, so it's
  deferred until a plain override isn't enough.
