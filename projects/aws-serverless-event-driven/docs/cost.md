# Cost

> **Illustrative and approximate.** Prices are us-east-1 list prices as
> understood at the time of writing, rounded, before free tier. They are not
> quotes. Verify against current AWS pricing. Nothing in this repo has been
> deployed or billed.

## What drives the bill

Everything here is pay per request, so cost scales with orders, and an idle
stack costs almost nothing (the KMS key's ~$1/month is the main fixed cost).

| Driver | Pricing basis | Lever |
|---|---|---|
| API Gateway HTTP API | Per request (~$1.00/M for the first 300M) | Already the cheap option: a REST API is ~$3.50/M |
| Lambda requests | ~$0.20/M invocations | Batching: up to 10 messages per processor invocation |
| Lambda duration | GB-seconds (~$0.0000133/GB-s on arm64, ~20% below x86) | arm64, right-sized memory, short handlers |
| SQS | ~$0.40/M requests (64 KB chunks); send + receive + delete | Long polling, batch receive and delete |
| DynamoDB on-demand | ~$0.625/M write units, ~$0.125/M read units | No reads in the hot path; small items (1 WCU each) |
| DynamoDB PITR + storage | ~$0.20/GB-month PITR, ~$0.25/GB-month storage | TTL deletes idempotency records for free |
| EventBridge custom bus | ~$1.00/M events published | One event per order |
| SNS | Per publish plus per delivery; email is the most expensive delivery type | A real consumer would subscribe SQS or Lambda, not email |
| CloudWatch Logs | ~$0.50/GB ingested, plus storage | Short JSON lines, INFO level, 14-day retention |
| CloudWatch alarms | ~$0.10 per standard alarm-month | 8 alarms, ~$0.80/month |
| KMS | ~$1/key-month plus requests | One key shared by both topics |

## Per-million-orders breakdown (approximate)

Assumptions: 1M accepted orders a month, 256 MB functions on arm64, ingest
~20 ms, processor ~60 ms per batch of 10 (with batching window), ~1 KB
messages, ~600 bytes of log per order, no retries, notifications delivered
to an SQS or Lambda subscriber rather than email.

| Component | Usage for 1M orders | Approx. cost |
|---|---|---|
| API Gateway HTTP API | 1M requests | $1.00 |
| Lambda ingest | 1M invocations + 1M x 0.02 s x 0.25 GB = 5,000 GB-s | $0.20 + $0.07 |
| Lambda process | 100k invocations + 100k x 0.06 s x 0.25 GB = 1,500 GB-s | $0.02 + $0.02 |
| SQS | ~1M sends + ~0.1-0.2M batched receives + ~0.1M batch deletes, plus empty long polls | ~$0.50 |
| DynamoDB writes | 3 writes/order (claim, order, complete) = 3M WRU | $1.88 |
| EventBridge | 1M custom events | $1.00 |
| SNS | 1M publishes + 1M deliveries to SQS/Lambda | ~$0.50 |
| CloudWatch Logs | ~0.6 GB ingested | $0.30 |
| **Variable total** | | **~$5.50 per million orders** |
| Fixed (alarms, KMS key, DynamoDB storage + PITR for ~1 GB) | per month | ~$2.25 |

Read the table for proportions, not precision. DynamoDB writes, API Gateway
and EventBridge are about 70% of the variable cost. The Lambda compute
the design is named after is under 10%. Batching on the consumer side is why
the processor's request cost is a tenth of ingest's.

What changes the picture:

- **Retries and poison messages.** Each failed delivery repeats SQS
  receives, a Lambda invocation share, and possibly DynamoDB writes. At
  `maxReceiveCount = 5`, a poison message costs about five times a good
  one. That's negligible unless a bug poisons everything, and the DLQ
  alarm catches that within minutes.
- **Logging at DEBUG.** Log ingestion can overtake every other line item.
- **Email notifications.** Fine for a demo; at volume, use a queue or a
  function subscriber.
- **Free tier.** Lambda's monthly free tier (1M requests, 400k GB-s) would
  cover the Lambda lines at this volume in many accounts.

## When containers win

Serverless is cheapest when traffic is spiky or low, and it buys
operational simplicity at any volume. A container service (ECS on Fargate,
or EKS when a cluster already exists) starts to win when:

- **Traffic is high and steady.** Per-request pricing keeps scaling
  linearly. A small always-on service handling a few hundred requests per
  second has a flat cost. The crossover depends on request duration and
  memory. As a rough guide, sustained tens of millions of requests a day
  with consistent load is where it's worth modelling. The API Gateway and
  EventBridge per-request charges usually matter more than Lambda's.
- **Work per request is long or heavy.** Lambda bills duration times memory,
  so CPU-bound or long I/O-bound work on large memory settings costs more than
  a reserved vCPU. Lambda's 15-minute limit rules some work out entirely.
- **Connection-heavy dependencies.** Relational databases without a proxy,
  or services that benefit from long-lived pooled connections and in-process
  caches, fit a long-running process better.
- **Commitment discounts apply.** Savings Plans cover Fargate and Lambda,
  but steady container workloads use the commitment more fully.

This pipeline's components are mostly managed queues, tables and buses that
cost the same either way. Moving the two functions into containers would
change only the compute lines, which are already the smallest. The
deciding factor would be operational: team skills, existing platform, and
latency requirements (cold starts are a few hundred milliseconds for this
small stdlib-only package on arm64; provisioned concurrency removes them at a
fixed cost).
