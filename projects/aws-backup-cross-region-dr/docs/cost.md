# Cost

> **Illustrative and approximate.** us-east-1 / us-west-2 list prices as
> understood at the time of writing, rounded, before free tiers and
> discounts. They are not quotes. AWS Backup pricing differs by resource
> type and region and changes over time, so check the AWS Backup, KMS,
> CloudWatch and data-transfer pricing pages before using any figure.
> Nothing in this repo has been deployed or billed.

## What drives the bill

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| Warm backup storage | ~$0.05 per GB-month for EBS, RDS and EFS warm backups. Incremental after the first full, for most types | Retention is the main lever: 35 daily + 13 weekly + 12 monthly points is not 60× the data, because snapshots are incremental, but churn adds up |
| Cold storage | ~$0.01 per GB-month, **minimum 90 days**, and only for types that support it (EFS, DynamoDB with advanced features, and a few others). RDS and Aurora snapshots don't tier | Only worth it for monthly or yearly points kept 6+ months. A point moved cold and deleted at day 100 pays for 90 days of cold anyway, so the policy checker enforces cold + 90 ≤ delete |
| Cross-region copy, transfer | Inter-region data transfer ~$0.02 per GB, charged on each copy (incremental for most types after the first) | Copy every gold rule, but only weekly for silver. Pick a DR region close enough that transfer and latency are sane |
| Cross-region copy, storage | The DR vault is billed like the primary: a second full set of points | Use a shorter DR retention for dailies if regional recovery only needs recent points (each rule has its own copy lifecycle) |
| Continuous backup (PITR) | Billed as warm storage of the changes (RDS: transaction logs and snapshots; S3: change records), roughly in line with the change rate | 35-day ceiling. Only gold daily uses it |
| Restore testing | No AWS Backup fee for the test itself. You pay for the **restored resources while they exist**: an RDS instance for the validation window, a DynamoDB table (restore charge per GB, ~$0.15/GB), S3 restore requests, EBS volume hours | Short validation windows (2-6 h). Smallest instance class through metadata overrides. Weekly, not daily |
| Restore data | Some types charge per GB restored (DynamoDB, EFS, S3 objects) | Restore a representative resource per type, not every resource, each week |
| KMS | ~$1 per key per month (four keys) + requests | |
| Lambda, EventBridge, SNS, alarms | Lambda runs a few seconds per test. AWS service events on the default bus are free. ~$0.10 per standard alarm | Negligible |
| Audit Manager | Per control evaluation plus AWS Config recording and rule evaluations | Optional. Enable it where an auditor asks for evidence |

## Example: a small gold/silver estate

Assumptions: one 200 GB RDS database and one 50 GB DynamoDB table in gold,
one 500 GB EBS volume in silver; ~3% daily change; gold copies everything
to DR; weekly restore tests of one RDS, one DynamoDB, one EBS and one small
S3 bucket, each held for 4 hours.

| Item | Monthly (approx.) |
|---|---|
| Primary warm storage (fulls + incrementals under the policy retentions), ~1.5 TB stored | ~$75 |
| DR warm storage (gold all rules + silver weekly), ~1 TB | ~$50 |
| Cross-region transfer for copies, ~400 GB/month of incrementals | ~$8 |
| PITR for the RDS instance (35 days of logs) | ~$10-20 |
| Restore tests: 4 × RDS db.t4g.medium for 4 h (~$0.07/h), DynamoDB restore of 50 GB (~$7.50 each), EBS volume hours | ~$35 |
| 4 KMS keys, alarms, Lambda, SNS | ~$6 |
| **Total** | **roughly $180-200 per month** |

The DynamoDB restore is the surprise line. A weekly full-table restore of a
large table costs more than its backups. For big tables, restore-test a
smaller representative table, or test monthly.

## Where the money goes at scale

- **Storage, by a wide margin.** Retention is a risk decision with a cost:
  every extra month of monthlies is a month of storage in two regions.
  Review retention against what you've actually needed to restore.
- **Churn, not size.** A 2 TB database that rewrites 20% a day costs far
  more to back up and copy than a 5 TB archive that barely changes.
- **Copies double storage.** That's the price of regional DR. A shorter DR
  lifecycle for daily copies (keep 7 days in DR, 35 in primary) is the
  usual trim, if the DR RPO only needs recent points. The policy checker
  would flag a gold DR copy below the tier minimum, so make that change in
  the minimums too, on purpose.
- **Compliance-mode lock removes the "delete it to save money" lever.**
  That's the point of it, but a mistakenly long retention becomes a fixed
  cost for its whole term.
