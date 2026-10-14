# ADR 0002: Partial batch responses for the SQS consumer

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-serverless-event-driven (portfolio implementation)

## Context

The processor receives up to 10 messages per invocation. By default, a Lambda
SQS consumer is all or nothing: if the handler raises, every message in the
batch becomes visible again and is retried, including those already
processed. With one bad message in a batch of ten:

- the nine good messages are reprocessed on every retry (safe only because
  of ADR 0001, and wasteful even so);
- all ten count a receive, so good messages can be pushed into the DLQ
  alongside the bad one after `maxReceiveCount` attempts;
- one poison message holds back unrelated orders for minutes.

Setting batch size to 1 avoids this but multiplies invocations (and their
cost) by up to ten.

## Decision

1. The event source mapping sets `function_response_types =
   ["ReportBatchItemFailures"]`.
2. The handler processes each record in isolation and **never raises for a
   single record**. It returns exactly
   `{"batchItemFailures": [{"itemIdentifier": "<messageId>"}, ...]}`, listing
   only the records that failed. Lambda deletes the rest.
3. Failures are classified in logs as **retryable** (`record_failed`: held
   lock, `PutEvents` failure, throttling) or **poison** (`poison_message`:
   invalid JSON, schema violation, unsupported version, payload hash
   mismatch, key reused with another payload). Both are reported as failed.
   The queue's redrive policy decides when to stop retrying.
4. Unhandled, whole-invocation errors (timeout, import error) still fail the
   whole batch. That is correct, because then no record's outcome is known,
   and it is exactly what the `Errors` alarm watches.

## Alternatives considered

- **Raise on any failure (default behaviour).** Rejected for the reasons in
  the context.
- **Batch size 1.** Simple and correct, but ~10x the invocations at volume,
  and it gives up the batching window that smooths load.
- **Send poison messages straight to the DLQ from the function** (`SendMessage`
  to the DLQ, then report success). That skips pointless retries, but the
  function then needs write access to the DLQ, the message loses its receive
  history, and quarantine becomes something the code must get right on
  every path. With `maxReceiveCount = 5`, a poison message costs four extra
  short invocations. That's cheap enough to keep one, declarative
  quarantine path. Revisit if poison messages become common, which would
  itself be the real problem.
- **Delete poison messages and log them.** Loses data that may be
  recoverable after a fix. The DLQ plus `start-message-move-task` keeps the
  option open for 14 days.

## Consequences

- One bad message no longer delays or endangers its batch neighbours. The
  test suite checks this (`test_partial_batch_failure_reports_only_failed_ids`,
  `test_poison_message_is_redriven_to_dlq_after_max_receives`).
- The response must contain *only* valid message IDs from the batch. An
  unknown or malformed `itemIdentifier` makes Lambda treat the whole batch as
  failed. The handler builds the list from the records it was given, and a
  test asserts the response has no other keys.
- The Lambda `Errors` metric no longer reflects per-record failures.
  Monitoring therefore relies on queue age and DLQ depth (both alarmed) and
  on the `poison_message`/`record_failed` log events.
- Every record path must catch its own exceptions. A bug that let one escape
  would quietly revert to all-or-nothing behaviour. The broad `except` in
  `process_record` is deliberate and covered by tests for each failure type.
