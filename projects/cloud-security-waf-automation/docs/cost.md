# Cost

> **Illustrative and approximate.** These are us-east-1 list prices as
> understood at the time of writing, rounded, before free tiers, trials and
> discounts. They are not quotes. AWS has repriced and renamed parts of this
> stack before (Security Hub's pricing and packaging changed in 2025), so
> check the current pricing pages before relying on any figure. Nothing in
> this repo has been deployed or billed.

## What drives the bill

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| WAF web ACL | ~$5 per web ACL per month | One ACL can protect several ALBs in a region |
| WAF rules | ~$1 per rule per month. Each managed rule group counts as one rule | Fold IP lists into one rule each. Don't add groups "just in case" |
| WAF requests | ~$0.60 per million requests inspected, for ACLs up to 1,500 WCUs | Stay under 1,500 WCUs: above it, each extra 500 WCUs adds ~$0.20 per million |
| Managed rule groups | The four used here (baseline and IP reputation groups) have **no subscription fee** beyond the rule charge | Bot Control, Account Takeover Prevention and Account Creation Fraud Prevention add monthly and per-request fees. Not used here |
| WAF logs | CloudWatch vended-log ingestion ~$0.50/GB (tiered down at volume) + storage | 30-day retention. Use a logging filter to drop ALLOW records once rollouts are done. S3 delivery is cheaper at volume |
| GuardDuty | Volume-based: per million CloudTrail management events analysed (~$4), per GB of VPC Flow Logs and DNS logs (~$1/GB at low volume, tiered), plus per-feature charges (S3, EKS, RDS, Lambda, Malware Protection) | A 30-day free trial shows the real estimate in the console. Enable optional protection plans deliberately |
| Security Hub | Per security check per account per region (~$0.001 per check at the first tier, cheaper at volume) plus finding ingestion beyond a free allowance (~$0.00003 per event) | FSBP only. Each additional standard multiplies check volume. Disable controls for services you don't use |
| KMS | ~$1 per key per month + requests | One CMK for both topics |
| SNS | Fractions of a cent per thousand notifications. Email is free at this volume | |
| EventBridge | AWS service events on the default bus are free. Rules are free | |
| CloudWatch alarm | ~$0.10 per standard alarm per month | |

## Example: the `examples/basic` stack

Assumptions: one web ACL with the allow list, block list, rate rule and four
managed groups (7 rules, ~1,130 WCUs); 10 million requests a month; about 1 KB
of log per request with all requests logged; GuardDuty and Security Hub in a
single small account.

| Item | Monthly (approx.) |
|---|---|
| Web ACL | $5 |
| 7 rules | $7 |
| 10 M requests | $6 |
| WAF logs, ~10 GB ingested, 30-day retention | ~$5 ingestion + <$1 storage |
| GuardDuty, small account (low CloudTrail volume, a few GB of flow and DNS logs) | ~$5-20 |
| Security Hub FSBP, a few hundred resources | ~$5-15 |
| KMS key, alarm, SNS | ~$1-2 |
| **Total** | **roughly $35-60 per month** |

WCU arithmetic (from the managed rule group capacities AWS lists):
CommonRuleSet 700, KnownBadInputs 200, SQLi 200, IpReputationList 25, rate
rule about 2, two IP-set rules 1 each. That's about 1,130, under the 1,500
included. Adding Bot Control (50 WCUs, plus its own fees) would still fit.
Adding a second large group would not.

## Where the money goes at scale

- **WAF requests and logs** grow linearly with traffic. At 1 billion
  requests a month, requests are ~$600 and logs dominate unless they're
  filtered or sent to S3.
- **GuardDuty** grows with CloudTrail and VPC flow volume, so busy
  accounts with chatty workloads cost the most. Usage statistics per data
  source are in the console.
- **Security Hub** grows with resource count times enabled controls. In a
  multi-account setup, a delegated administrator with central
  configuration avoids duplicate standards in every account.

The CI policy check costs nothing extra beyond GitHub Actions minutes (a few
seconds per run).
