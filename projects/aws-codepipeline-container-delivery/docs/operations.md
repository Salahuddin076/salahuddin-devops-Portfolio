# Operations

> This stack has been validated with `terraform validate` only and never
> deployed by the author. The steps below are how it is meant to be operated:
> rehearse them in a sandbox account, don't read them as a record of
> production use.

## Bootstrap

Prerequisites: Terraform >= 1.6, AWS credentials from the standard SDK chain,
an existing VPC with at least two private subnets that can reach ECR,
Secrets Manager and CloudWatch Logs (NAT gateway or VPC endpoints), and admin
access to the GitHub organisation that owns the repository.

The first deploy has a chicken-and-egg problem: the services need an image,
and the image comes from the pipeline. The example handles it with
`first_apply = true`, which creates both services at `desired_count = 0`.

1. **Apply with zero tasks.**

   ```bash
   cd terraform/examples/basic
   cp terraform.tfvars.example terraform.tfvars   # real vpc_id, subnet_ids, repository
   terraform init
   terraform plan -out tfplan     # first_apply = true
   terraform apply tfplan
   ```

2. **Complete the CodeConnections handshake (manual, once).** Terraform
   creates the connection in `PENDING` state. AWS requires a person to
   authorise the GitHub App: Console > Developer Tools > Settings >
   Connections > select `delivery-demo-github` > *Update pending connection* >
   install or choose the GitHub App for the organisation, limited to this
   repository. The status must read `Available`. Until it does, every Source
   action fails with a connection error. This step cannot be automated with
   Terraform, by design: it is the GitHub-side consent.

3. **Set the secret values out of band.** Terraform creates the secrets
   without a version, so no value is ever in state or plan output:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id delivery-demo/staging/db \
     --secret-string file://staging-db.json     # {"username":"app","password":"..."}
   aws secretsmanager put-secret-value \
     --secret-id delivery-demo/prod/db --secret-string file://prod-db.json
   aws secretsmanager put-secret-value \
     --secret-id container-delivery/ci/dockerhub --secret-string file://dockerhub.json
   shred -u staging-db.json prod-db.json dockerhub.json 2>/dev/null || rm -P staging-db.json prod-db.json dockerhub.json
   ```

   Use `file://` rather than an inline `--secret-string '...'` so the value
   doesn't land in shell history. The JSON keys must be exactly `password`
   (DB) and `username` / `password` (registry), because the references select
   those keys ([troubleshooting](troubleshooting.md)).

4. **Run the pipeline once.** Push to `main`, or
   `aws codepipeline start-pipeline-execution --name delivery-demo-delivery`.
   The deploy actions register revisions with the commit SHA image and update
   services that still have zero tasks. The deploys succeed trivially.

5. **Scale up.** Set `first_apply = false` and apply again. Terraform changes
   only `desired_count`. It ignores `task_definition`, so the services start
   the pipeline's revision, not the `:bootstrap` placeholder.

## Releasing

A release is a merge to `main`. With `trigger_file_paths` set (the example
uses the project directory), pushes elsewhere in the monorepo don't start the
pipeline.

What happens, in order:

1. **Test** runs `check_buildspec.py` and the unit tests and publishes
   `<prefix>-test-unit-tests` in CodeBuild > Report groups.
2. **Build** tags the image with `CODEBUILD_RESOLVED_SOURCE_VERSION` (the
   40-character commit SHA), scans it, pushes it and writes
   `imagedefinitions.json`. The Trivy report is in
   `<prefix>-build-image-scan`.
3. **DeployStaging** rolls staging. The action waits for the ECS deployment
   to complete (up to 20 minutes).
4. **ApproveProd** emails the approval topic and waits up to
   `approval_timeout_minutes` (24 hours by default).
5. **DeployProd** rolls prod with the same artifact.

Checking what's running:

```bash
aws ecs describe-services --cluster delivery-demo-cluster \
  --services delivery-demo-staging delivery-demo-prod \
  --query 'services[].{svc:serviceName,td:taskDefinition,rollout:deployments[0].rolloutState}'
```

The app also reports its own version: `GET /version` returns `APP_VERSION`
and `GIT_SHA`, baked into the image at build time.

## Approving

Before approving, check that staging is serving the commit in the approval
message (`/version` on a staging task, or the task definition image tag),
that the staging deployment shows `COMPLETED`, and that the staging logs show
no `startup_refused` or error spike.

```bash
aws codepipeline get-pipeline-state --name delivery-demo-delivery \
  --query 'stageStates[?stageName==`ApproveProd`].actionStates[0].latestExecution.token' --output text
aws codepipeline put-approval-result --pipeline-name delivery-demo-delivery \
  --stage-name ApproveProd --action-name ManualApproval \
  --result summary="staging verified",status=Approved --token <token>
```

Rejecting fails the execution, and prod keeps running the previous release.
Because the pipeline runs in `QUEUED` mode, the next commit waits behind the
one being approved and is never silently promoted in its place.

Who may approve is an IAM question: grant `codepipeline:PutApprovalResult`
on `arn:aws:codepipeline:<region>:<account>:delivery-demo-delivery/ApproveProd/ManualApproval`
to the release approvers only. In this single-account demo, nothing prevents
the author of a commit from also approving it. Enforce separation of duties
with the IAM grant above or an approval rule elsewhere.

## Rolling back

There are three situations. Each has a different answer.

**1. The new tasks never become healthy.** Examples: the image fails to start,
the secret doesn't resolve, or `/healthz` fails. The deployment circuit
breaker trips and ECS rolls the service back to the last completed
deployment automatically. The deploy action fails, and the stage's
`on_failure = ROLLBACK` re-runs it with the previous successful artifact.
Nobody needs to act except to find the cause:

```bash
aws ecs describe-services --cluster delivery-demo-cluster --services delivery-demo-staging \
  --query 'services[0].events[:10].message'
aws ecs list-tasks --cluster delivery-demo-cluster --service-name delivery-demo-staging --desired-status STOPPED
aws ecs describe-tasks --cluster delivery-demo-cluster --tasks <arn> --query 'tasks[0].stoppedReason'
```

**2. The release is healthy but wrong** (bad behaviour, not a crash). The
circuit breaker can't see it. Redeploy a previous SHA. The fastest safe way
is to point the service at the previous task definition revision, which
already references the previous immutable image:

```bash
aws ecs describe-task-definition --task-definition delivery-demo-prod:41 \
  --query 'taskDefinition.containerDefinitions[0].image'     # confirm the SHA
aws ecs update-service --cluster delivery-demo-cluster \
  --service delivery-demo-prod --task-definition delivery-demo-prod:41
```

Or use the pipeline's own rollback, which redeploys the artifact of an
earlier successful execution and keeps the pipeline history accurate:

```bash
aws codepipeline rollback-stage --pipeline-name delivery-demo-delivery \
  --stage-name DeployProd --target-pipeline-execution-id <earlier-successful-execution-id>
```

Then fix forward with a revert commit. That revert goes through the
pipeline like any other release, so `main` and prod agree again.

**3. The previous image has been expired.** The ECR lifecycle policy keeps
the last `ecr_keep_images` images (50 by default). Older SHAs need a rebuild:
revert to that commit on `main` and let the pipeline build it. Never re-tag
an image by hand: the tags are immutable, and the pipeline would have no
record of the deploy.

## Routine tasks

- **Rotate the DB password.** `put-secret-value` with the new JSON, then
  force a new deployment of each service
  (`aws ecs update-service --force-new-deployment ...`). ECS resolves
  `secrets` only when a task starts, so running tasks keep the old value
  until they are replaced.
- **Bump Trivy.** Change `TRIVY_VERSION` in `buildspec-build.yml`. The
  checksum file is verified, but it comes from the same release, so read the
  release notes before upgrading.
- **Bump the base image.** Change the tag (ideally the digest) in
  `app/Dockerfile`, merge, and let the pipeline scan the result.
- **Investigate a CRITICAL finding.** Open the `image-scan` report group, or
  run `trivy image <uri>` locally. Fix it by bumping the base image or the
  dependency. Accepting a finding means a `.trivyignore` entry with an expiry
  and a reason, reviewed like code.

## Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| Source action: "connection is not available" | Handshake not completed, or the GitHub App lost access to the repo | Connections console; GitHub org > Settings > GitHub Apps |
| Build: `CODEBUILD_RESOLVED_SOURCE_VERSION is not a commit SHA` | Build started outside the pipeline (console "Start build" without a source version) | Start it from the pipeline |
| Build: `secrets-manager` env fails with `ResourceNotFoundException` | Registry secret has no value yet, or the name differs from the buildspec | Step 3 above; `registry_secret_name` |
| Build: Docker login fails, or `toomanyrequests` | Wrong registry credentials, or the anonymous pull limit | Registry secret JSON keys |
| Build: Trivy exits 1 | A CRITICAL finding: working as intended | `image-scan` report |
| Build: `ImageTagAlreadyExistsException` on push | The same commit was rebuilt. Tags are immutable | Re-run the deploy stages only, or retry the execution |
| Deploy: tasks stop with `ResourceInitializationError: unable to pull secrets` | No route to Secrets Manager, or the secret has no value | Subnet routes and endpoints; secret versions |
| Deploy: tasks start, then `startup_refused` in the logs | `DB_PASSWORD` missing, or the whole JSON was injected | [troubleshooting.md](troubleshooting.md) |
| Deploy: action times out with no failed tasks | Fargate capacity or ENI limits in the subnets, or tasks stuck PENDING on image pull | Service events |
| App: `CannotPullContainerError ... :bootstrap` | `first_apply = false` before the first pipeline run | Bootstrap steps 4-5 |

For buildspec secret pitfalls, see [troubleshooting.md](troubleshooting.md).
