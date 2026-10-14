# Security

The aim: each stage can do only its own step, against only this stack's
resources, and no secret value appears in source, Terraform state, build
logs or application logs. Everything below is in
[`terraform/modules/container-delivery`](../terraform/modules/container-delivery)
and the buildspecs. Nothing has been deployed.

## IAM per stage

Every role trusts exactly one service principal, with an `aws:SourceAccount`
condition (CodeBuild roles also pin `aws:SourceArn` to their own project).
No AWS managed policies are attached anywhere.

### CodeBuild test (`<prefix>-codebuild-test`)

| Action | Resource | Why |
|---|---|---|
| `logs:CreateLogStream`, `logs:PutLogEvents` | its own log group | Build logs |
| `s3:GetObject`, `s3:GetObjectVersion` | artifact bucket objects | Read the source zip; **no `PutObject`**, it produces no artifact |
| `kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey` | the stack key | Artifact encryption |
| `codebuild:CreateReportGroup`, `CreateReport`, `UpdateReport`, `BatchPutTestCases` | `report-group/<prefix>-test-*` | JUnit results |

The test stage has no ECR, Secrets Manager or ECS access. Code under test
runs here, so a malicious test can't push an image or read a secret.

### CodeBuild build (`<prefix>-codebuild-build`)

Everything the test role has, plus `s3:PutObject` for `imagedefinitions.json`, and:

| Action | Resource | Why |
|---|---|---|
| `ecr:GetAuthorizationToken` | `*` | Registry login; the action has no resource-level permissions |
| `ecr:BatchCheckLayerAvailability`, `InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage`, `BatchGetImage`, `GetDownloadUrlForLayer` | **this repository ARN only** | Push the image |
| `secretsmanager:GetSecretValue` | **the registry secret ARN only** | Docker Hub login for base image pulls |

It can't read the DB secrets, call ECS, or delete images. With
`codebuild_in_vpc = true` it also gets the EC2 network-interface actions
CodeBuild needs, and `ec2:CreateNetworkInterfacePermission` is conditioned
on `ec2:AuthorizedService = codebuild.amazonaws.com` and the configured
subnets.

The build project runs in **privileged mode**, which `docker build`
requires. Privileged mode is why the build is a separate project from the
test stage, and why the build role is kept so narrow.

### CodePipeline (`<prefix>-pipeline`)

| Action | Resource | Why |
|---|---|---|
| `s3:GetObject`, `GetObjectVersion`, `PutObject`; `GetBucketVersioning`, `GetBucketLocation` | artifact bucket | Move artifacts between stages |
| `kms:Decrypt`, `Encrypt`, `GenerateDataKey`, `DescribeKey` | the stack key | Artifacts and the encrypted SNS topic |
| `codeconnections:UseConnection`, `codestar-connections:UseConnection` | the one connection | Source; both prefixes because the service was renamed |
| `codebuild:StartBuild`, `BatchGetBuilds` | the two projects | Run Test and Build |
| `ecs:DescribeServices`, `UpdateService` | **the two service ARNs** | Deploy |
| `ecs:RegisterTaskDefinition`, `DescribeTaskDefinition` | `*` | No resource-level permissions for these |
| `ecs:DescribeTasks`, `ListTasks` | `*` with `ecs:cluster` = this cluster | Watch the rollout |
| `ecs:TagResource` | `task-definition/<prefix>-*`, only when `ecs:CreateAction = RegisterTaskDefinition` | Tag new revisions, nothing else |
| `iam:PassRole` | the four ECS roles, only to `ecs-tasks.amazonaws.com` | The deploy action passes execution and task roles to the new revision |
| `sns:Publish` | the approval topic | Notify approvers |

`RegisterTaskDefinition` on `*` combined with `PassRole` is the most
powerful pair here. Without the `PassRole` restriction, the pipeline could
register a task definition that uses any role in the account. With it, the
pipeline can attach only the stack's own task roles, and those roles hold
only the permissions listed below.

### ECS execution roles (one per environment)

Used by the ECS agent before the container starts. Application code
never sees these credentials.

| Action | Resource | Why |
|---|---|---|
| `ecr:GetAuthorizationToken` | `*` | Registry login |
| `ecr:BatchCheckLayerAvailability`, `BatchGetImage`, `GetDownloadUrlForLayer` | this repository | Pull, read-only |
| `logs:CreateLogStream`, `logs:PutLogEvents` | that environment's log group | Container logs |
| `secretsmanager:GetSecretValue` | **that environment's DB secret only** | Resolve `secrets` |
| `kms:Decrypt` | the stack key, only `kms:ViaService = secretsmanager.<region>.amazonaws.com` | Decrypt the secret, and nothing else |

The staging execution role can't read the prod secret.

### ECS task roles (one per environment)

Empty. The demo app calls no AWS APIs. A role with no policy is the
correct starting point: add permissions per environment when the app needs
them, and keep them off the execution role.

## Secrets flow

```text
operator ──put-secret-value (out of band)──▶ Secrets Manager (CMK)
                                               │
          ┌────────────────────────────────────┴───────────────────────────┐
          ▼                                                                ▼
CodeBuild build: env.secrets-manager                    ECS: task definition `secrets`
  DOCKERHUB_PASSWORD: "<name>:password"                  DB_PASSWORD: "<arn>:password::"
  (masked in build logs)                                 (resolved by the execution role
                                                          at task start, env var in the container)
```

- **No value in Terraform.** The module creates `aws_secretsmanager_secret`
  resources without an `aws_secretsmanager_secret_version`. A version
  resource would put the plaintext in state, and in plan output whenever
  it changed. Values are set with `put-secret-value` (see
  [operations](operations.md#bootstrap)).
- **No value in the buildspec.** Secrets come from `env: secrets-manager`
  with the `secret-id:json-key` form. `check_buildspec.py` fails the Test
  stage if a secret-looking name (`PASSWORD`, `SECRET`, `TOKEN`, `API_KEY`,
  ...) appears under `env: variables`, or if a secrets-manager reference
  lacks the JSON key (rules BS002 and BS003). CodeBuild masks
  secrets-manager values in its logs. The registry password is passed with
  `--password-stdin`, never as an argument.
- **No value in the app's output.** `DB_PASSWORD` is excluded from the
  config `repr`, never returned by an endpoint, and a logging filter
  replaces the value with `***` if any log record would contain it. The
  access log records the path without the query string. Tests prove each
  of these by starting the real server with a sentinel password and
  searching every log line and response for it. One test runs the entrypoint
  as a subprocess and checks its whole stdout and stderr.
- **Fail fast on a wrong shape.** With `REQUIRE_DB_PASSWORD=true` (set in the
  task definition), the app refuses to start if the variable is missing or
  looks like a whole JSON document, the symptom of a reference without
  `:json-key`. It logs the reason, never the value. The circuit breaker then
  rolls the deploy back.
- **Environment variables are visible to anyone who can describe the task
  from inside it.** That's acceptable for this threat model. The stricter
  alternative is to fetch the secret at runtime with the task role and
  cache it in memory, which also lets you rotate without a redeploy.

## Image supply chain

| Control | Where |
|---|---|
| Multi-stage build; the runtime stage has only the three app files | `app/Dockerfile` |
| Non-root user (UID 10001), read-only root filesystem in ECS, port above 1024 | Dockerfile, task definition |
| Base image pinned by exact tag (`python:3.12.12-slim-bookworm`); digest pinning recommended | Dockerfile comment |
| Trivy gate: `--exit-code 1 --severity CRITICAL` before `docker push` | `buildspec-build.yml`, enforced by lint rules BS006/BS007 |
| Trivy report (HIGH and CRITICAL) published as a JUnit report group | `buildspec-build.yml` |
| Trivy binary downloaded by pinned version, checksum verified | `buildspec-build.yml` install phase |
| Immutable tags, the commit SHA only; `latest` refused by lint (BS005) and by `make_imagedefinitions.py` | ECR, scripts |
| ECR scan on push (basic scanning) as a second signal | `ecr.tf` |
| ECR encrypted with the stack CMK | `ecr.tf` |

Gaps worth naming: the Trivy checksum file comes from the same GitHub
release as the binary, so it detects corruption, not a compromised release.
Pin the tarball's SHA-256 in the buildspec, or bake Trivy into a custom build
image, for a stronger guarantee. There is no image signing (cosign or AWS
Signer) and no admission check that only signed images run. HIGH findings
are reported but don't fail the build. That's a policy choice to revisit
per team.

## Artifact bucket

- **SSE-KMS with the stack CMK**, with S3 Bucket Keys enabled to cut KMS
  request costs. The pipeline's `artifact_store` uses the same key.
- **Public access block**, all four settings on, and `BucketOwnerEnforced`
  object ownership, so ACLs are disabled.
- **TLS-only bucket policy.** It denies `s3:*` when
  `aws:SecureTransport = false`.
- **Versioning plus lifecycle.** Artifacts expire after
  `artifact_retention_days` (30), noncurrent versions after 7 days, and
  incomplete multipart uploads after 1 day.
- `imagedefinitions.json` contains an image URI, not a secret. The source
  zip does contain the whole repository, which is the reason for the
  encryption and the short retention.

## KMS key

One customer managed key, with rotation enabled. The key policy delegates
to IAM (the account root statement), so each role's access is visible in
its own policy. CloudWatch Logs is the one service principal in the key
policy, limited by `kms:EncryptionContext:aws:logs:arn` to this stack's log
group names. One key keeps the demo readable. A production setup would
often split keys by data class (artifacts vs secrets) so that key policy
alone can separate who decrypts what.

## Gaps on purpose for a portfolio stack

- Single account. Production would run the pipeline in a tooling account
  and deploy cross-account into staging and prod accounts, with the artifact
  key shared through key policy.
- No load balancer, WAF or TLS termination. The service has no inbound
  access unless `ingress_cidr_blocks` is set.
- No separation-of-duties enforcement on approvals beyond IAM.
- ECR enhanced scanning (Inspector) isn't enabled. It is a registry-level
  setting and usually belongs to the account baseline, not this module.
