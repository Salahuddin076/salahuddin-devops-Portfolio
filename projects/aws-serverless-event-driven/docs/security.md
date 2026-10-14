# Security

The aim is that a compromised or buggy function can do only what its code
does, against only this stack's resources. Everything below is in
[`terraform/modules/order-pipeline`](../terraform/modules/order-pipeline);
nothing has been deployed.

## IAM: one role per function

Both roles trust `lambda.amazonaws.com` with an `aws:SourceAccount`
condition, so the roles can't be assumed through a function in another
account (confused-deputy protection). There are no managed policies.
`AWSLambdaBasicExecutionRole` would add `logs:CreateLogGroup` on `*`, and
Terraform already creates the log groups with a retention period. A group
created by Lambda on first invocation would keep logs forever.

### ingest

| Action | Resource | Why |
|---|---|---|
| `logs:CreateLogStream`, `logs:PutLogEvents` | its own log group | Write logs |
| `sqs:SendMessage` | the orders queue | Enqueue the validated order |

Ingest can't read the queue, touch DynamoDB or publish events. Even with
code execution in that function, the most an attacker can do is enqueue
messages, and the processor re-validates every one (schema, `schemaVersion`,
and a payload hash) before acting.

### process

| Action | Resource | Why |
|---|---|---|
| `logs:CreateLogStream`, `logs:PutLogEvents` | its own log group | Write logs |
| `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` | the orders queue | Used by the event source mapping on the function's behalf |
| `dynamodb:PutItem` | the table | Idempotency claim (conditional) and the order record |
| `dynamodb:UpdateItem` | the table | Mark a claim `COMPLETED` with its result |
| `dynamodb:DeleteItem` | the table | Release a claim after a failure |
| `events:PutEvents` | the custom bus | Publish `OrderAccepted` |

Deliberately absent:

- **`dynamodb:GetItem`, `Query`, `Scan`.** Duplicates read the blocking item
  from the failed conditional write (`ReturnValuesOnConditionCheckFailure =
  ALL_OLD`), which also saves a round trip. The processor can't enumerate
  orders.
- **`sqs:SendMessage` on the DLQ.** Quarantine is the queue's redrive policy,
  not something the function decides.
- **`sqs:ChangeMessageVisibility`.** Not needed with partial batch responses.
- **`kms:*`.** SQS uses SQS-managed SSE and DynamoDB its AWS owned key, so
  neither requires KMS permissions on the role.

A further tightening would be `dynamodb:LeadingKeys` conditions restricting
the role to `IDEMPOTENCY#*` and `ORDER#*` keys. It isn't added because those
are the only item types in the table.

## Resource policies

- **SNS notifications topic.** EventBridge may `sns:Publish` only when
  `aws:SourceArn` is exactly the `order-accepted` rule ARN; any other rule,
  including one in another account, is refused. Publishing over plain HTTP is
  denied.
- **SNS alarms topic.** CloudWatch may publish only for alarms named
  `<prefix>-*` in this account and region.
- **KMS key (both topics).** Account administration plus
  `kms:GenerateDataKey*`/`kms:Decrypt` for `events.amazonaws.com` and
  `cloudwatch.amazonaws.com`, limited by `aws:SourceAccount`. The AWS managed
  `alias/aws/sns` key can't be used because its policy can't grant those
  services. Rotation is on.
- **SQS queues.** Both deny any action without TLS (`aws:SecureTransport =
  false`). The DLQ's `redrive_allow_policy` accepts only the orders queue.
- **Lambda permission.** API Gateway may invoke ingest only from this API's
  `/orders` route (`source_arn` scoped to the execution ARN).

## Data protection

| Store | At rest | Notes |
|---|---|---|
| SQS queue + DLQ | SQS-managed SSE | No KMS cost or key policy to manage |
| DynamoDB | AWS owned key (always on), PITR enabled | Switch to a customer managed key if key usage must appear in CloudTrail |
| SNS topics | Customer managed KMS key, rotation on | Required by EventBridge/CloudWatch publishing to encrypted topics |
| CloudWatch Logs | Service default encryption, 14-day retention (90 in prod) | Logs contain order IDs, customer IDs and correlation IDs, not payment data |

The order contract has no card numbers, addresses or names, so nothing in
the logs or the event is sensitive. A real order would carry PII, and the
logs and event would then need a field allowlist.

## Input handling

- Strict validation at the edge: unknown fields are rejected, integers are
  bounded, `bool` isn't accepted as a number, SKUs and customer IDs are
  matched against patterns, and the body is capped at 16 KB (`413` above it).
- The client-supplied `X-Correlation-Id` is echoed into logs, so only
  `[A-Za-z0-9._:-]{1,128}` is accepted. Anything else (newlines, for log
  injection) is replaced with a generated ID.
- The processor treats the queue as untrusted and re-validates, so a message
  injected by any other producer with `SendMessage` rights can't skip checks.

## Gaps, on purpose for a portfolio stack

- **No authentication on `POST /orders`.** A real deployment would add a JWT
  authorizer (Cognito or an OIDC provider) on the route and scope the
  idempotency key per client (`<clientId>#<key>`), so one client can't
  collide with another's keys.
- **No AWS WAF.** Stage throttling limits volume but doesn't filter abuse.
  WAF in front of the HTTP API requires CloudFront, since HTTP APIs can't be
  associated with WAF directly.
- **No X-Ray tracing.** The correlation ID covers request tracing in logs.
  Active tracing would need `xray:PutTraceSegments` on both roles.
- **No VPC.** The functions only call AWS APIs, so a VPC would add NAT or
  endpoint cost without reducing exposure.
