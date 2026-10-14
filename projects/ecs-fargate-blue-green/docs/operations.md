# Operations

Runbook for the blue/green platform. Nothing here has been run against a
real account; the commands follow the AWS CLI v2 reference. Replace
`prod` with `dev` or `staging` as needed. Names follow the module:
CodeDeploy application and deployment group `bluegreen-<env>`, service
`bluegreen-<env>` in cluster `bluegreen-cluster`.

## Bootstrap (once)

1. Lint the settings: `python3 scripts/check_bluegreen_policy.py`.
2. Apply `terraform/environments/shared` (ECR repository and ECS cluster).
3. Push a first image with an immutable tag (the commit SHA), built for
   ARM64:
   `docker buildx build --platform linux/arm64 --build-arg IMAGE_TAG=$SHA -t $REPO:$SHA --push app`.
4. Package the hooks (next section).
5. Apply each environment root with `bootstrap_image = "$REPO:$SHA"`. Each
   creates that environment's ALB; point its host name (`dev.api.example.com`,
   `staging.api.example.com`, `api.example.com`) at the root's
   `alb_dns_name` output with an alias record.
6. Set the secret value out of band, so it never enters Terraform state:
   `aws secretsmanager put-secret-value --secret-id bluegreen/prod/db --secret-string file://prod-db.json`
   (a JSON object with a `password` key; the file is git-ignored).

## Packaging the hooks

The hook Lambdas are the four files in `src/hooks/`, zipped flat
(boto3 comes from the Lambda runtime):

```bash
mkdir -p build && python3 -m zipfile -c build/hooks.zip src/hooks/*.py
```

`hooks_zip_path` defaults to `../../../build/hooks.zip` from each
environment root. Changing the zip changes `source_code_hash`, so the next
apply updates both functions.

## Triggering a deployment

A release is: register a task definition revision with the new image, then
ask CodeDeploy to move the service to it.

```bash
SHA=3f9c2b1e7a4d5c6b8e9f0a1b2c3d4e5f6a7b8c9d
REPO=123456789012.dkr.ecr.us-east-1.amazonaws.com/bluegreen-api

# 1. values: the static ones come from `terraform output render_values`
cp deploy/values.example.json build/values.json   # then edit for the environment

# 2. task definition
python3 scripts/render_appspec.py --values build/values.json --only taskdef \
  --set IMAGE=$REPO:$SHA --out-dir build
TASKDEF_ARN=$(aws ecs register-task-definition --cli-input-json file://build/taskdef.json \
  --query taskDefinition.taskDefinitionArn --output text)

# 3. appspec pointing at that revision
python3 scripts/render_appspec.py --values build/values.json --only appspec \
  --set TASK_DEFINITION_ARN=$TASKDEF_ARN --out-dir build

# 4. deployment
aws deploy create-deployment \
  --application-name bluegreen-prod \
  --deployment-group-name bluegreen-prod \
  --description "release $SHA" \
  --revision "$(python3 -c 'import json,sys; print(json.dumps({"revisionType": "AppSpecContent", "appSpecContent": {"content": open("build/appspec.yaml").read()}}))')"
```

The deployment uses the group's `deployment_config_name` unless
`--deployment-config-name` overrides it. Don't override prod to
`ECSAllAtOnce`; the lint blocks that in the settings for a reason.

`render_appspec.py` refuses `latest` and untagged images, and derives
`IMAGE_TAG` from the image so the hooks check the tag ECS actually pulls.
In CodePipeline (`CodeDeployToECS` action) the appspec would carry
`<TASK_DEFINITION>` and the task definition `<IMAGE1_NAME>` instead; that
path is not built here.

## Watching it

```bash
DEPLOYMENT_ID=d-EXAMPLE111
aws deploy get-deployment --deployment-id $DEPLOYMENT_ID \
  --query 'deploymentInfo.[status,deploymentOverview,errorInformation]'
aws deploy get-deployment-target --deployment-id $DEPLOYMENT_ID \
  --target-id bluegreen-cluster:bluegreen-prod \
  --query 'deploymentTarget.ecsTarget.[status,lifecycleEvents[].[lifecycleEventName,status],taskSetsInfo[].[identifer,trafficWeight,status]]'
aws ecs describe-services --cluster bluegreen-cluster --services bluegreen-prod \
  --query 'services[0].taskSets[].[id,status,taskDefinition,runningCount,computedDesiredCount]'
aws logs tail /aws/lambda/CodeDeployHook_bluegreen-prod-before-allow-traffic --follow
```

(`identifer` is the field's actual spelling in the CodeDeploy API.) Each
hook logs one JSON line with the status, the passed checks, the failures
and the measured p95.

To see what a config will do before running it:

```bash
python3 scripts/traffic_shift_sim.py --config CodeDeployDefault.ECSCanary10Percent5Minutes \
  --minutes 70 --termination-wait 60 --events-only
```

## Manual reroute and approval (prod)

Prod sets `manual_reroute = true`. After green is healthy and reachable on
the test listener (`https://api.example.com:8443`), the deployment waits
in `Ready` for up to 60 minutes. Test it from an allowed CIDR, then:

```bash
aws deploy continue-deployment --deployment-id $DEPLOYMENT_ID --deployment-wait-type READY_WAIT
```

If nobody continues within `reroute_wait_minutes`, the deployment is
stopped (`action_on_timeout = STOP_DEPLOYMENT`) and production never moved.
Who may call `continue-deployment` is the approval: grant
`codedeploy:ContinueDeployment` on the prod deployment group to the
release approvers only, separately from whoever creates deployments.

Blue stays up for 60 minutes after the full shift. To end the wait early
once you're confident:
`aws deploy continue-deployment --deployment-id $DEPLOYMENT_ID --deployment-wait-type TERMINATION_WAIT`.

## Stopping and rolling back

```bash
# stop and move traffic back to the original task set
aws deploy stop-deployment --deployment-id $DEPLOYMENT_ID --auto-rollback-enabled
```

Automatic rollback also happens on `DEPLOYMENT_FAILURE` (green unhealthy,
a hook reports Failed, a hook times out) and `DEPLOYMENT_STOP_ON_ALARM`.
Both are listener changes while blue still exists.

After blue is terminated there is nothing to switch back to. Roll back by
deploying the previous task definition revision (the ECR lifecycle keeps
50 images, and old revisions still reference them): render the appspec with
the previous `TASK_DEFINITION_ARN` and run `create-deployment` again.

## Common failures

### Green never becomes healthy

Symptoms: deployment stuck in `Install`, then failed; targets `unhealthy`
in the replacement target group.

- `aws elbv2 describe-target-health --target-group-arn <green-arn>`: the
  reason code tells you which. `Target.Timeout` usually means the task
  security group doesn't allow the ALB on the container port, or the app
  isn't listening on `PORT`.
- `Target.ResponseCodeMismatch`: `/healthz` isn't returning 200.
- Tasks stopping: `aws ecs describe-tasks` shows `stoppedReason`. Common
  ones are a missing `:json-key` on the secret, an image built for the
  wrong architecture (`exec format error`: the image is x86 but the task
  definition says ARM64), or ECR pull denied (wrong repository ARN on the
  execution role).

### Hook timeout

Symptoms: the deployment sits in `BeforeAllowTraffic` for up to an hour,
then fails.

- The hook never called `PutLifecycleEventHookExecutionStatus`. The code
  reports from a `finally` block, so this means the Lambda was killed
  (timeout, out of memory) or the report call itself was denied. Check
  the hook log group and the Lambda's `Errors`/`Duration` metrics.
- The hook stops itself when less than one request timeout plus 5 seconds
  of Lambda time is left, then reports Failed. Keep
  `smoke_requests × smoke_request_timeout_seconds` well under the 300 s
  Lambda timeout.
- **Hook can't reach the test listener**: the requests time out. The hook
  runs in private subnets and reaches the ALB through NAT, so each NAT
  gateway's EIP must be a `/32` in `test_listener_cidrs`. Check the hook
  security group allows egress to the test port.
- `AccessDenied` on the report: the hook role only allows the deployment
  group `bluegreen-<env>` in this account and region.

### `ignore_changes` drift confusion

- **"I changed the task definition in Terraform and nothing deployed."**
  Correct. The service ignores `task_definition`; Terraform registers a new
  revision, but only CodeDeploy moves the service. Release through
  `create-deployment`. Keep `deploy/taskdef.template.json` aligned with
  `ecs.tf` (container name, port, secrets, logs).
- **"The plan wants to change the listener back to blue."** It shouldn't:
  both listeners ignore `default_action`. If someone removed the
  `ignore_changes`, an apply after an even-numbered deployment would point
  production back at the target group with no tasks. That's an outage.
  Restore the lifecycle block.
- **"The service's load_balancer shows blue but green is live."** Expected.
  ECS keeps the original load balancer config; the live target group is
  the one in the production listener's default action. Ask CodeDeploy or
  the listener, not Terraform.
- **"Apply failed changing the capacity provider strategy or network
  configuration."** Services on the `CODE_DEPLOY` controller accept only a
  few changes through `UpdateService`. Put the new values into the
  appspec (`CapacityProviderStrategy`, `NetworkConfiguration`) and deploy,
  or recreate the service in a maintenance window.

### Alarm stopped a healthy deployment

The alarms watch both target groups. A burst of 5xx on the original group
during a deployment also rolls back, which is the conservative choice.
Check which alarm fired in the deployment's `errorInformation`, and the
alarm history in CloudWatch. Tune thresholds in `config/environments/<env>.json`;
the lint still requires alarms in prod.

### Spot interruption mid-deployment

In dev (Spot only) a reclaim can take green tasks while CodeDeploy waits
for them to be healthy; ECS replaces them, and the deployment either waits
it out or fails and rolls back. Staging and prod keep an on-demand base.
