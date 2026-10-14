# Operations

> This stack has been validated with `terraform validate` only and never
> deployed by the author. The steps below are how it is meant to be operated;
> treat them as a runbook to rehearse in a sandbox account, not a record of
> production use.

## Deploy

Prerequisites: Terraform >= 1.6, AWS credentials from the standard SDK chain
(SSO profile or environment), and a sandbox account you are allowed to
create resources in.

```bash
cd terraform/examples/basic
cp terraform.tfvars.example terraform.tfvars   # set environment, alarm_emails
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

- The Lambda zip is built by `archive_file` from `src/` into
  `terraform/examples/basic/.build/` (git-ignored). Changing any handler
  changes `source_code_hash` and redeploys both functions.
- Each email subscriber receives a confirmation mail and gets nothing until
  they confirm.
- `processor_reserved_concurrency` comes out of the account's concurrency
  pool. New accounts can have a low limit (and Lambda keeps 100 unreserved),
  so request an increase first if `apply` fails on `PutFunctionConcurrency`.
- `table_deletion_protection` is on for `prod` in the example. `destroy`
  needs it switched off first.

Smoke test:

```bash
ENDPOINT=$(terraform output -raw orders_endpoint)
curl -sS -X POST "$ENDPOINT" \
  -H 'content-type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'X-Correlation-Id: smoke-001' \
  -d '{"customerId":"cus_smoke0001","currency":"USD","items":[{"sku":"MUG-01","quantity":1,"unitPriceCents":900}]}'
# expect 202 {"correlationId": "smoke-001", "orderId": "ord_...", "status": "ACCEPTED"}
```

Then confirm the order in Logs Insights (both function log groups):

```text
fields @timestamp, service, message, order_id
| filter correlation_id = "smoke-001"
| sort @timestamp asc
```

You should see `order_enqueued` (ingest) and `order_accepted` (process).

## Redriving the DLQ

Messages land in the DLQ only after `maxReceiveCount` failed deliveries
(5 by default), so **find and fix the cause before redriving**. A poison
message redriven unchanged will fail again and come back.

1. Look at what's there without consuming it (a short visibility timeout
   returns the messages to the DLQ):

   ```bash
   DLQ_URL=$(terraform output -raw dlq_url)
   aws sqs receive-message --queue-url "$DLQ_URL" \
     --max-number-of-messages 10 --visibility-timeout 30 \
     --message-attribute-names All --attribute-names All
   ```

2. Find the reason in the processor logs. Every failed attempt logged
   `poison_message` (non-retryable) or `record_failed` (retryable) with the
   message ID:

   ```text
   fields @timestamp, message, reason, receive_count, correlation_id
   | filter message_id = "<messageId>"
   | sort @timestamp asc
   ```

3. Deploy the fix (or, for a one-off bad message, delete it and record why).

4. Move the messages back to the source queue:

   ```bash
   aws sqs start-message-move-task \
     --source-arn "$(terraform output -raw dlq_arn)" \
     --destination-arn "$(terraform output -raw queue_arn)" \
     --max-number-of-messages-per-second 10

   aws sqs list-message-move-tasks --source-arn "$(terraform output -raw dlq_arn)"
   # cancel if needed:
   aws sqs cancel-message-move-task --task-handle "<TaskHandle>"
   ```

   Redrive is safe to repeat: orders that were in fact processed before
   failing (for example, the event published but the claim not marked
   complete) are skipped or republished with the same event ID.
   The DLQ only accepts messages from the orders queue
   (`redrive_allow_policy`), and the move task needs `sqs:StartMessageMoveTask`
   and related permissions on the operator's role, not on the Lambdas.

5. Rate-limit the move (`--max-number-of-messages-per-second`) so a large
   backlog doesn't saturate the processor's reserved concurrency.

## Alarm runbooks

All alarms notify the `<prefix>-alarms` topic, on both ALARM and OK.

### dlq-not-empty

`ApproximateNumberOfMessagesVisible > 0` on the DLQ. Every message there is
an order that was accepted by the API (`202`) but not processed.

1. Check whether it's one message or a stream: a burst at the same time
   points to a deploy or a dependency outage; a trickle points to bad input.
2. Follow [Redriving the DLQ](#redriving-the-dlq).
3. If a deploy caused it, roll back first, then redrive.

### queue-oldest-message-age

Oldest message older than `oldest_message_age_alarm_seconds` (300 s by
default) for 3 of 5 minutes. Processing is behind or stuck.

- **Processor throttled or at max concurrency:** check `ConcurrentExecutions`
  against `processor_max_concurrency`; raise both it and reserved
  concurrency if downstream can take it.
- **Most deliveries failing:** check `record_failed` in the logs. A held
  idempotency lock (`another invocation holds the idempotency lock`) clears
  by itself after `timeout + 5 s`.
- **Event source mapping disabled:** `aws lambda list-event-source-mappings
  --function-name <prefix>-process` should show `State: Enabled`.

### lambda-errors

`Errors > 0` in 2 of 3 minutes. For **ingest** this means unhandled
exceptions (the client got a 5xx). For **process** it means the whole
invocation failed: import errors, timeouts, out of memory, or bad
configuration (missing `TABLE_NAME`). Per-record failures don't count here
because they are returned as `batchItemFailures`.

1. Logs Insights on the function's log group:
   `filter @message like /Task timed out|Runtime.ImportModuleError|ERROR/`.
2. Check the last deploy (`source_code_hash` changed) and roll back if it
   lines up.
3. Timeouts: compare `Duration` p99 to the timeout; DynamoDB or EventBridge
   latency is the usual cause.

### lambda-throttles

`Throttles > 0`. For **process**, this shouldn't happen while
`processor_max_concurrency <= processor_reserved_concurrency` (a Terraform
precondition enforces it), so check for a manual change to reserved
concurrency. For **ingest**, the account's unreserved concurrency is
exhausted by something else: find the noisy function, or give ingest
reserved concurrency.

### eventbridge-failed-invocations

The rule could not deliver to SNS after 24 retries over an hour. Usually a
policy problem: the SNS topic policy must allow `events.amazonaws.com` with
`aws:SourceArn` equal to the rule ARN, and the KMS key policy must let
EventBridge use the key. Check CloudTrail for `AccessDenied` on `Publish`
or `GenerateDataKey`. Orders are still recorded; only the notification was
lost. Consider a DLQ on the target if notifications must never be lost.

### api-5xx

More than five 5xx responses a minute for 2 of 3 minutes. Either ingest is
failing (see `lambda-errors`) or SQS rejected writes (`enqueue_failed` logs,
returned as `503`). Clients are told to retry with the same
`Idempotency-Key`, so no orders are duplicated.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `400 Idempotency-Key: header is required` | Client didn't send the header | Header name is case-insensitive; value 8-128 chars `[A-Za-z0-9._:-]` |
| Same order shows twice downstream | Consumer not deduping on event `id` | Event delivery is at least once by design |
| Retry returns `202` but nothing new happens | Working as intended: duplicate skipped | `duplicate_skipped` log line with `stored_result` |
| `poison_message: idempotency key reused with a different payload` | Client reused a key for a different order | Fix the client; keys must be unique per order |
| `record_failed: PutEvents failed` | EventBridge throttling or permissions | `events:PutEvents` on the bus ARN; `PutEvents` quota for the region |
| No email notifications | Subscription not confirmed, or KMS key policy | `aws sns list-subscriptions-by-topic`; key policy statement `AllowServicePublishersToEncrypt` |
| `AccessDeniedException` on `dynamodb:GetItem` | Code change added a read | The role grants only `PutItem`/`UpdateItem`/`DeleteItem` on purpose; add the action to `iam.tf` if the read is needed |
