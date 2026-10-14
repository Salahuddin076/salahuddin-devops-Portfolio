# Cost

> **Illustrative and approximate.** These are us-east-1 list prices as
> understood at the time of writing, rounded, before free tiers, credits,
> Savings Plans and enterprise discounts. They are not quotes, and AWS
> changes prices. Check the pricing pages before relying on any figure.
> Nothing in this repository has been deployed or billed.

## What drives the bill

Organizations, SCPs, tag policies, IAM Identity Center, RAM and the Config
aggregator itself cost nothing. The money is in the network hub and, at
scale, in logging and Config.

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| **Transit Gateway attachments** | ~$0.05 per attachment-hour, so **~$36 per attachment per month**. Every spoke VPC and the egress VPC is one | Fewer, larger spokes. Don't attach VPCs that never talk to anything. Sandbox has no hub access by design |
| **Transit Gateway data processing** | ~$0.02 per GB sent into the TGW | Keep chatty pairs in one VPC. Use VPC endpoints for AWS APIs instead of going through the hub |
| **NAT gateways** | ~$0.045 per hour each (**~$33/month**) plus ~$0.045 per GB processed, plus a public IPv4 address at ~$0.005/hour (~$3.60/month) | One per AZ in the hub instead of one per AZ per spoke (the point of [ADR 0003](decisions/0003-centralized-egress.md)). Gateway endpoints for S3 and DynamoDB are free and keep that traffic off NAT |
| Internet data transfer out | ~$0.09 per GB (first tier) | Not specific to the landing zone, but central egress makes it visible |
| CloudTrail org trail | The first copy of management events in each account is **free**. Data events ~$0.10 per 100,000 (not enabled here). S3 storage and KMS requests are billed separately | Don't create a second management-event trail: the second copy costs ~$2 per 100,000 events |
| Log storage | S3 Standard ~$0.023 per GB-month, Glacier Flexible Retrieval ~$0.0036 per GB-month, transition requests ~$0.05 per 1,000 objects | CloudTrail writes many small objects, so transition requests can cost more than the storage they save. Check object count, not just GB |
| AWS Config | ~$0.003 per configuration item recorded (continuous); rule evaluations ~$0.001 each for the first 100,000 per month; conformance pack evaluations similar | Periodic recording for noisy resource types, record only the types you have rules for, and don't deploy the same rules twice (org rules plus Security Hub controls) |
| KMS | ~$1 per key per month plus ~$0.03 per 10,000 requests | S3 Bucket Keys on the log bucket (enabled) cut the KMS requests from CloudTrail and Config writes substantially |
| Budgets, SNS | The first budgets per account are free, then cents per budget per day. SNS email is free at this volume | |
| Access Analyzer | External-access analyzers are free. Unused-access analyzers are billed per IAM role and user analyzed (not used here) | |

## Example: the synthetic organization

Assumptions: six member accounts; five spoke VPCs plus the egress VPC on the
TGW; two AZs with a NAT gateway each; 1 TB a month of spoke traffic to the
internet and 500 GB between spokes and shared services; a small Config
footprint (~2,000 configuration items per account per month, ~20 org rules);
a few GB of CloudTrail logs a month.

| Item | Monthly (approx.) |
|---|---|
| TGW attachments: 6 × ~$36 | ~$220 |
| TGW data processing: 1.5 TB × $0.02 | ~$30 |
| NAT gateways: 2 × ~$33 | ~$66 |
| NAT public IPv4: 2 × ~$3.60 | ~$7 |
| NAT data processing: 1 TB × $0.045 | ~$45 |
| Config: ~12,000 items + rule evaluations | ~$40-80 |
| CloudTrail org trail (management events, first copy) | $0 |
| Log storage, KMS (Bucket Keys), lifecycle requests | ~$5-15 |
| Budgets, SNS, Access Analyzer, Organizations, Identity Center | ~$0-2 |
| **Total (before internet data transfer out)** | **roughly $410-470 per month** |

Internet data transfer out for that 1 TB adds roughly $90, but it's paid
with or without a landing zone.

## The two big ones

- **Transit Gateway** is about half of this bill, and it's mostly the
  attachment-hours, not the traffic. Every new spoke adds ~$36 a month
  before a single packet. That's why Sandbox accounts don't attach, and why
  "one VPC per microservice" gets expensive fast. Per-GB processing then
  grows with east-west traffic.
- **NAT gateways** come second, and they scale with bytes. Every byte to
  the internet pays TGW processing (~$0.02) **plus** NAT processing
  (~$0.045) before transfer-out. Traffic to AWS services (S3, ECR, STS,
  CloudWatch) is the usual surprise. Gateway endpoints (S3, DynamoDB) are
  free, and interface endpoints in the shared-services VPC (~$7-8 per AZ
  per month each, plus ~$0.01/GB) pay for themselves at modest volume.

Central egress saves money compared with NAT per spoke: five spokes × two
AZs × ~$33 is ~$330 a month in NAT hours alone, against ~$66 here. It
costs the TGW processing on every byte. Below a few spokes, NAT per VPC
can be cheaper. See [ADR 0003](decisions/0003-centralized-egress.md).

## At scale

- **Config** grows with resource churn. Autoscaling groups and ephemeral
  containers generate configuration items continuously, and Config can
  overtake the network in a large organization.
- **CloudTrail data events** (S3 object-level, Lambda invoke) are where
  trail costs explode. Enable them selectively, with advanced event
  selectors.
- **Log storage** is cheap per GB but accumulates for the retention period.
  Seven years of Glacier is still cheap, but Object Lock means you can't
  delete early if you over-collect.
