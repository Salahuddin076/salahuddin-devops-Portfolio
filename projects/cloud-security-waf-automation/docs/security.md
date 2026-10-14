# Security

What each control protects, what it doesn't, and the security properties of
the automation itself. Nothing has been deployed. Statements about AWS
behaviour come from AWS documentation, not observation.

## Threats covered, and by what

| Threat | Control | Limits |
|---|---|---|
| Known malicious IPs, scanners | `AWSManagedRulesAmazonIpReputationList`, block list | Reputation lists lag. Attackers rotate through cloud and residential IPs |
| Request floods, credential stuffing from one source | `rate-limit-per-ip` (per IP, 5-minute window) | Distributed attacks stay under a per-IP limit. Shield Advanced and bot control are out of scope |
| OWASP-style payloads (XSS, LFI, oversize bodies) | `AWSManagedRulesCommonRuleSet` | Signature-based. It's no substitute for output encoding and input validation |
| Exploit strings (Log4Shell, Java deserialisation) | `AWSManagedRulesKnownBadInputsRuleSet` | Only known patterns |
| SQL injection | `AWSManagedRulesSQLiRuleSet` (optional, starts in count) | No substitute for parameterised queries |
| Infrastructure misconfiguration shipped by a PR | `check_plan.py` gate | Only the six rules it has (see below), and only on resources in the plan |
| Compromised credentials or instances | GuardDuty, routed by severity | Detection, not prevention. Time-to-contain depends on the responder |
| Configuration drift after deploy | Security Hub FSBP controls | Periodic checks. HIGH findings go to tickets, not pages |

## WAF logging

- **Redaction.** `authorization` and `cookie` headers are redacted in the
  logging configuration, so they appear as `REDACTED` in every log record.
  Bearer tokens and session cookies never land in CloudWatch, where many
  more people can read them than can read the application. Add other
  headers (`x-api-key`) through `redacted_headers`.
- **Still sensitive.** Logs contain client IPs, URIs and query strings,
  which can be personal data and can contain tokens passed in URLs.
  Retention defaults to 30 days. Encrypt with `log_kms_key_arn` and
  restrict `logs:GetLogEvents` on `aws-waf-logs-*`.
- **Delivery permission.** The module declares the CloudWatch Logs resource
  policy for `delivery.logs.amazonaws.com`, scoped by `aws:SourceAccount`
  and `aws:SourceArn`, rather than relying on AWS to add a broader one
  implicitly. There's a limit of 10 resource policies per region, so
  `create_log_resource_policy = false` turns this off where one exists.

## Allow list risk

`ip-allow-list` terminates evaluation with ALLOW, so every later rule is
skipped for those addresses. Only put fixed, owned ranges in it (a
synthetic-monitoring range, for example). Never put a CDN or a shared egress
range there. Review it like an IAM admin grant.

## Notification path

- **CMK encryption** with rotation enabled. The key policy grants
  `kms:GenerateDataKey*` and `kms:Decrypt` only to `events.amazonaws.com` and
  `cloudwatch.amazonaws.com`, conditioned on `aws:SourceAccount`. The account
  root keeps administration so the key can't become unmanageable.
- **Topic policies** allow `sns:Publish` from EventBridge only for the
  routing rules that target that topic (`aws:SourceArn`). They allow
  CloudWatch alarms from this account, and deny publishing without TLS.
- **No finding content beyond the summary line** goes to email. The input
  transformer sends type, severity, account, region and finding ID.
  Responders open the console for the details, which keeps resource
  details and IPs out of mailboxes.
- **Retries.** Targets retry for up to an hour (10 attempts). There's no
  dead-letter queue yet (see README limitations).

## Secrets rotation: why there is no Lambda here

The module takes an **existing** rotation Lambda ARN and wires
`aws_secretsmanager_secret_rotation`. It doesn't build the function, on purpose:

- AWS publishes maintained rotation templates for RDS, Aurora, Redshift,
  DocumentDB and generic single-user and alternating-user schemes. You
  deploy them from the Serverless Application Repository, or through
  `ManageMasterUserPassword` for RDS, where AWS rotates without any Lambda
  you own.
- A hand-rolled rotation function is security-critical code. It has to
  implement the four steps (`createSecret`, `setSecret`, `testSecret`,
  `finishSecret`), handle staging labels and retries, run in the VPC with
  database access, and be patched. A portfolio copy would be untested
  against a real database and worse than the template.
- The interesting parts for this project are the wiring and its
  preconditions: the Lambda's resource policy must allow
  `secretsmanager.amazonaws.com`, its role must be able to read and write
  that one secret, and the database must be reachable from its subnets.
  The input variable validates the ARN shapes. The rest is documented
  here because Terraform can't check it.

## The policy checker itself

- **Fails closed on bad input.** An unreadable plan, a plan without
  `resource_changes`, or a malformed or incomplete exceptions file exits 2,
  and CI treats that as a failure. An IAM policy that isn't valid JSON is
  reported as a finding, not skipped.
- **Fails open on unknowns, explicitly.** An IAM policy whose document is
  unknown at plan time (computed from a data source) is skipped, since the
  checker can't judge it. That's documented in the README. Checkov and
  OPA have the same gap with unknown values.
- **Exceptions are narrow.** Exact rule ID plus resource address, a
  mandatory owner, reason and expiry, expired entries ignored and
  reported. Nothing excepts a whole rule or a whole module.
- **SARIF upload permission is scoped.** Only the SARIF job in CI gets
  `security-events: write`. Everything else runs with `contents: read`.

## What the six rules don't cover

Encryption at rest for S3, EBS, DynamoDB and SNS; public RDS
(`publicly_accessible`); IMDSv2 enforcement; KMS key policies;
`iam:PassRole` scope; trust policies that are too broad; logging on ALB and
S3; and every non-AWS provider. A real organisation needs hundreds of
checks, which is the main argument for Checkov or OPA in
[ADR 0002](decisions/0002-stdlib-policy-checker-vs-opa-checkov.md).
