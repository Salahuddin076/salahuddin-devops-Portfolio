# Operations

Runbooks for the four routine jobs: rolling out a WAF rule, handling a WAF
false positive, triaging a GuardDuty finding and adding a policy exception.
All commands use documentation placeholders (`123456789012`,
`edge-demo-web-acl`). Nothing here has been run against a real account.

## Count-then-block rollout

Every new rule or rule group starts in **count** mode: it matches and logs,
but doesn't block. Flip it to **block** only when the logs show it would
block attackers and not customers. [ADR 0001](decisions/0001-count-before-block.md)
explains why.

**1. Add the rule in count mode.** In the example, the SQLi group starts that way:

```hcl
AWSManagedRulesSQLiRuleSet = { priority = 40, mode = var.sqli_mode }   # sqli_mode = "count"
```

Apply through the normal pipeline. `terraform output rule_modes` shows the
current state of every rule.

**2. Collect at least one full business cycle of logs.** One week is a good
default. It should cover month-end jobs, batch imports, the mobile app's
release and anything else that only runs sometimes. Export the window as
JSON lines (GNU `date`; on macOS use `date -u -v-7d +%s`):

```bash
aws logs filter-log-events \
  --log-group-name aws-waf-logs-edge-demo \
  --start-time "$(date -u -d '7 days ago' +%s)000" \
  --query 'events[].message' --output json \
  | python3 -c 'import json,sys; [print(m) for m in json.load(sys.stdin)]' > waf-week.jsonl
```

(For large volumes, use a CloudWatch Logs export to S3, or Logs Insights
with `filter action = "ALLOW" and ispresent(nonTerminatingMatchingRules.0.ruleId)`.)

**3. Run the summary and read the flip-to-block section:**

```bash
python3 scripts/waf_log_summary.py waf-week.jsonl
```

```text
Count-mode matches that would block (flip-to-block review):
  rate-limit-per-ip  [count-mode rule]
      matches 6, would newly block 6, unique IPs 1, top URI /login (6/6)
      hint: concentrated on few clients: likely hostile, candidate to block
  AWSManagedRulesSQLiRuleSet/SQLi_BODY  [count-mode group]
      matches 5, would newly block 5, unique IPs 5, top URI /api/reports/query (5/5)
      hint: many clients on one path: check for a false positive (scope-down or exclusion) first
```

How to read it:

- **would newly block** counts only requests that were allowed. Matches
  on requests something else blocked anyway don't change anything when
  you flip.
- **Few IPs, many requests** (the rate rule above): one client hammering
  `/login`. Blocking it is the intent.
- **Many distinct clients on one path** (`SQLi_BODY` on
  `/api/reports/query`): almost always a legitimate feature whose payload
  looks like an attack, here a report builder that posts SQL-like filter
  text. Flipping now would break that feature for every user. Handle the
  false positive first (next section).
- The hint is a heuristic, not a verdict. Before flipping, pull a few
  sampled requests (`aws wafv2 get-sampled-requests`) or the raw log lines
  for the top IPs and URIs, and look at them.

**4. Flip to block.** Set `sqli_mode = "block"` and apply. The output
`rule_modes` and the PR diff are the change record.

**5. Watch for an hour.** The `edge-demo-waf-blocked-requests-spike` alarm
pages if blocks exceed the threshold, which is also what a bad flip looks
like. Rolling back means setting `mode = "count"` again and applying: a
one-line revert, no rule deletion, and the rule keeps logging.

## Handling a false positive

Symptom: users report 403s on a specific feature, or the flip-to-block view
shows many distinct clients matching one rule on one path.

**1. Confirm it.** Find the requests and the exact rule:

```bash
python3 scripts/waf_log_summary.py --json waf-today.jsonl \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["top_blocked_rules"], indent=2))'
```

Then look at the raw log lines for that URI. In them,
`ruleGroupList[].terminatingRule.ruleId` names the rule inside the group.

**2. Choose the narrowest fix.** In order of preference:

| Option | When | How |
|---|---|---|
| **Fix the request** | The app sends something it doesn't need to (an oversize body, a raw SQL string) | Change the application. Nothing to weaken in the WAF |
| **Scope-down** | The rule is right everywhere except one path | Add a `scope_down_statement` to the managed group so it skips, for example, `uri_path` starting with `/api/reports/`. The rest of the site keeps full protection |
| **Rule override to count** (exclusion) | One rule in a group misfires broadly for this app | Add it to `rules_to_count` for that group. It keeps matching and logging, so you can still see it |
| **Group to count** | Many rules in the group misfire at once | Emergency only: `mode = "count"`, then work back to block |

The example already carries one exclusion. `SizeRestrictions_BODY` (8 KB
body limit) is overridden to count because avatar uploads exceed it:

```hcl
AWSManagedRulesCommonRuleSet = { priority = 20, mode = "block", rules_to_count = ["SizeRestrictions_BODY"] }
```

The summary keeps reporting it as `[rule override]`, so the exclusion stays
visible rather than turning into forgotten configuration. The module
supports `rules_to_count` directly. A scope-down statement is the better fix
when the false positive is confined to a path. Adding one is a small change
to the managed-group block in `modules/waf/main.tf`, and it's listed under
limitations in the README.

**3. Record why** in the PR description: the rule, the evidence (counts,
URI, client spread), the option chosen and a date to revisit.

## Triage a GuardDuty finding

The page arrives as one line, for example:

```text
[PAGE] GuardDuty severity 8 UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration.OutsideAWS in 123456789012/us-east-1. Finding 3ac5b2e0f1d9EXAMPLE.
```

**1. Acknowledge and pull the finding:**

```bash
DETECTOR=$(aws guardduty list-detectors --query 'DetectorIds[0]' --output text)
aws guardduty get-findings --detector-id "$DETECTOR" --finding-ids 3ac5b2e0f1d9EXAMPLE \
  --query 'Findings[0].{type:Type,sev:Severity,resource:Resource,action:Service.Action,first:Service.EventFirstSeen,last:Service.EventLastSeen,count:Service.Count}'
```

**2. Decide in about 15 minutes: real, benign or unknown.**

- *Which principal or resource?* `Resource.AccessKeyDetails` or
  `Resource.InstanceDetails`.
- *Is it still happening?* Compare `EventLastSeen` with now and look at
  `Service.Count`.
- *Is there a known benign explanation?* A pen test, a new CI runner
  range or a VPN change. Check the change calendar.
- *What else did the principal do?* CloudTrail Lake or Event history,
  filtered on the access key, for the window around `EventFirstSeen`.

**3. If it's real or unknown, contain before you investigate further.**
Typical containment by finding family:

| Finding family | Contain |
|---|---|
| `UnauthorizedAccess:IAMUser/*`, credential exfiltration | Deactivate the access key. For role credentials, attach a deny-all inline policy with an `aws:TokenIssueTime` condition, which revokes active sessions |
| `CryptoCurrency:EC2/*`, `Backdoor:EC2/*`, `Trojan:EC2/*` | Swap the instance's security group for an isolation SG with no rules. Snapshot the volumes for forensics. Don't terminate yet |
| `Recon:*`, `PortProbeUnprotectedPort` | Usually ticket-level. Close the exposed port. Consider adding the source range to the WAF block list if it targets HTTP |
| `Exfiltration:S3/*`, `Policy:S3/*` | Block public access on the bucket, review the bucket policy, rotate any exposed credentials |

**4. Record and close.** Archive or set the Security Hub workflow status
(`NOTIFIED` while you work, `RESOLVED` when done) so it stops re-alerting.
If it was benign and will recur, add a GuardDuty suppression rule with a
narrow filter, not a severity change.

Medium findings (4.0-6.9) arrive on the ticket topic and follow the same
steps within a working day. Low findings aren't routed. Review them weekly
in the console.

## Add a policy exception

When `check_plan.py` fails a PR and the finding is accepted for a while,
don't weaken the rule. Add an exception to `policy/exceptions.json`:

```json
{
  "rule_id": "CSP-SG-001",
  "resource": "aws_vpc_security_group_ingress_rule.legacy_bastion_ssh",
  "owner": "platform-team@example.com",
  "reason": "Vendor appliance only supports SSH from its dynamic IPv6 range; replacement with SSM Session Manager tracked in SEC-142",
  "expires": "2027-03-31"
}
```

Rules for exceptions:

- **All five fields are required.** The checker exits 2 on a malformed
  file, so a sloppy exception breaks the build, not the control.
- **The match is exact**: one rule ID on one resource address. There are
  no wildcards. A new resource with the same problem fails again.
- **The expiry is mandatory and short.** 90 days is a reasonable maximum.
  An exception is valid through its expiry date. After that it's ignored,
  the finding fails the build again, and the output lists it as
  `EXPIRED`, so the owner knows why.
- **Review in the PR.** The diff to `exceptions.json` is the approval
  record. Use CODEOWNERS to require a security reviewer on that file.
- Unused exceptions are reported as `UNUSED`. Delete them once the
  resource is fixed.

Excepted findings still appear in SARIF, as suppressed results with the
owner and reason as the justification. Code scanning shows them as
dismissed rather than letting them disappear.
