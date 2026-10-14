# Operations

Runbooks for the platform. Commands use synthetic names (`n8n-prod`,
`platform-prod`, account `123456789012`). Nothing here has been run against
a real account: this repo only validates.

## Install

Order matters. Each step depends on the one before.

1. **KEDA** (once per cluster). KEDA is not an EKS add-on, and this repo keeps
   Terraform to AWS resources (no Helm provider), so it is a pinned
   `helm install`:

   ```bash
   helm repo add kedacore https://kedacore.github.io/charts
   helm upgrade --install keda kedacore/keda --version 2.17.2 \
     --namespace keda --create-namespace
   ```

   The ServiceAccount must be `keda/keda-operator` (the chart's default), which
   is what the Terraform Pod Identity association expects. Check the KEDA
   release notes before moving off 2.17.x: the `aws` pod identity provider and
   `awsSecretManager` used here need 2.15 or later.

2. **Secrets Store CSI driver + AWS provider** (once per cluster): the
   `aws-secrets-store-csi-driver-provider` EKS add-on, plus the
   `eks-pod-identity-agent` add-on. The sibling project
   `projects/eks-secrets-store-csi` installs both with Terraform.

3. **Terraform, phase 1: secrets and network.** The ElastiCache AUTH token is
   read from Secrets Manager at apply time (an ephemeral read into the
   write-only `auth_token_wo`), so the secret needs a value before the
   replication group is created:

   ```bash
   terraform apply -target=module.n8n_platform.aws_secretsmanager_secret.redis_auth \
                   -target=module.n8n_platform.aws_secretsmanager_secret.encryption_key \
                   -target=module.n8n_platform.aws_secretsmanager_secret.db_app
   aws secretsmanager put-secret-value --secret-id n8n/redis-auth \
     --secret-string "$(openssl rand -hex 32)"
   aws secretsmanager put-secret-value --secret-id n8n/encryption-key \
     --secret-string "$(openssl rand -base64 48)"
   ```

   Generate both on a trusted workstation, never in CI logs. Back up the
   encryption key somewhere separate from the account (see below).

4. **Terraform, phase 2: everything else.** `terraform apply`. Then create the
   application role in Postgres as the RDS master user (fetch its password from
   the RDS-managed secret, output `db_master_secret_arn`):

   ```sql
   CREATE ROLE n8n_app LOGIN PASSWORD '<generated>';
   GRANT ALL ON DATABASE n8n TO n8n_app;
   GRANT ALL ON SCHEMA public TO n8n_app;
   ```

   and put `{"username":"n8n_app","password":"<generated>"}` into
   `n8n/db-app-credentials`.

5. **The chart.** Feed the Terraform outputs into the values:

   ```bash
   helm upgrade --install n8n helm/n8n-platform -n n8n --create-namespace \
     -f helm/n8n-platform/values-prod.yaml \
     --set database.host=<db_endpoint> --set redis.host=<redis_primary_endpoint> \
     --set "securityGroupsForPods.groupIds[0]=<pod_security_group_id>"
   kubectl -n n8n rollout status deploy/n8n-main     # runs the DB migrations
   kubectl -n n8n get scaledobject n8n-worker        # READY True, ACTIVE False when idle
   ```

## Upgrading n8n

Main runs the database migrations at start-up. Workers and webhook pods on
the old version must not run against a migrated schema, and new workers must
not start before the migrations finish.

1. Read the release notes for breaking changes and the migration list.
2. Snapshot the database: `aws rds create-db-snapshot --db-instance-identifier n8n-prod-db --db-snapshot-identifier n8n-pre-2-42`.
3. Stop the workers so nothing runs during the migration. KEDA owns the
   replica count, so pause it rather than scaling the Deployment:

   ```bash
   kubectl -n n8n annotate scaledobject n8n-worker autoscaling.keda.sh/paused-replicas="0" --overwrite
   kubectl -n n8n get deploy n8n-worker -w           # wait for 0; running jobs drain first
   ```

   Webhooks keep accepting calls and queueing jobs during the upgrade; they wait in
   `bull:jobs:wait` until workers return.
4. Bump `image.tag` and `helm upgrade`. Main is `Recreate`: the old main stops,
   the new one migrates (its readiness probe stays 503 until `migrated` is true;
   the startup probe allows 5 minutes), then webhook pods roll.
5. Unpause: `kubectl -n n8n annotate scaledobject n8n-worker autoscaling.keda.sh/paused-replicas-`.
   KEDA wakes the workers on the queued backlog.

Rolling back after a migration means restoring the snapshot: n8n migrations
are forward-only in practice.

## The encryption key can't be rotated casually

`N8N_ENCRYPTION_KEY` encrypts every stored credential (API keys, OAuth
tokens, passwords) in the `credentials_entity` table. Change it and n8n can no
longer decrypt any of them: every workflow that uses a credential fails, and
the old values are unrecoverable without the old key. It is also cached in
`/home/node/.n8n/config` (an in-memory emptyDir here); n8n refuses to start if
that file and the env disagree.

So the key is treated as a root secret:

- generated once; no automatic rotation on the Secrets Manager secret;
- a 30-day recovery window, and a copy in an offline vault;
- the same value in every pod (CP008 in `check_chart_policy.py` fails a pod that
  has no key: it would generate its own and fail to read credentials).

If it must change (suspected leak): export credentials decrypted with the old
key (`n8n export:credentials --all --decrypted --output=creds.json`, inside a
main pod, in a maintenance window), put the new key, restart everything, import
(`n8n import:credentials --input=creds.json`), then destroy the export. Then
rotate the *underlying* third-party credentials too, because a leaked key plus
a DB dump exposes them.

## Rotating the Redis AUTH token

ElastiCache accepts two tokens during a rotation (`redis_auth_token_update_strategy`, passed to `auth_token_update_strategy`).

1. `aws secretsmanager put-secret-value --secret-id n8n/redis-auth --secret-string "$(openssl rand -hex 32)"`.
2. Bump `redis_auth_token_version` and apply: ElastiCache now accepts both (`ROTATE`).
3. Roll the n8n pods so they read the new file (n8n reads `_FILE` values once
   at start): `kubectl -n n8n rollout restart deploy/n8n-main deploy/n8n-webhook deploy/n8n-worker`.
   KEDA re-reads the secret on its own.
4. Apply again with `redis_auth_token_update_strategy = "SET"` to drop the old token.

## Recovering stuck executions

Symptoms: executions listed as "running" for longer than `EXECUTIONS_TIMEOUT`,
or `bull:jobs:active` non-zero with no worker running.

- **A worker was killed mid-run** (OOM, node loss). n8n sets Bull's
  `maxStalledCount` to 0, so a stalled job is not re-run automatically, and
  main's queue recovery (`N8N_EXECUTIONS_QUEUE_RECOVERY_INTERVAL`) marks the
  orphaned executions as crashed. Retry them from the UI. A retry is a *new*
  execution with `retryOf` set; workflows with side effects should use the
  idempotency pattern in `scripts/duplicate_job_guard.py`.
- **Jobs pile up and nothing scales.** See troubleshooting below.
- **Inspect the queue.** The n8n image has no `redis-cli`. Run one from a
  short-lived pod in the namespace (it isn't selected by the n8n
  NetworkPolicies), with the token fetched by someone allowed to read it:

  ```bash
  TOKEN=$(aws secretsmanager get-secret-value --secret-id n8n/redis-auth --query SecretString --output text)
  kubectl -n n8n run redis-debug --rm -it --image=valkey/valkey:8.1 --restart=Never -- \
    valkey-cli --tls -h <redis_primary_endpoint> -a "$TOKEN" LLEN bull:jobs:wait
  ```

  Also useful: `LLEN bull:jobs:active`, `ZCARD bull:jobs:failed`. The token ends
  up in the pod spec this way, so treat it as a break-glass action and let
  `--rm` delete the pod. With security groups for pods on, the debug pod also
  needs a security group the cache accepts.

## Tuning `listLength`

`listLength` is the backlog one worker is expected to absorb before another
is added: replicas = `ceil(LLEN(wait) / listLength)`.

- Start at the worker concurrency (10). One more worker per 10 waiting jobs
  roughly doubles throughput as the backlog doubles.
- **Short jobs (seconds):** raise it (20-50). The queue drains between polls, and
  a low value spawns pods that start after the work is gone.
- **Long jobs (minutes):** lower it (2-5). A waiting job waits a full run per
  slot, so react early.
- `activationListLength`: 0 wakes workers for a single job (lowest latency). A
  higher value batches trickles, at the cost of jobs waiting until the backlog
  passes it. Note that scheduled workflows also go through the queue.
- Test a change on the sample, or on an exported depth series, before applying:
  `python3 scripts/keda_scaling_sim.py depth.csv --values helm/n8n-platform/values-prod.yaml --list-length 5`.

Pod start-up time (image pull, CSI mount, n8n boot: tens of seconds) is the
latency floor from zero. If that matters, set `minReplicaCount: 1` during
business hours (a KEDA `cron` trigger) and keep zero at night.

## Draining the node that runs main

In prod, main's PDB is `maxUnavailable: 0`, so `kubectl drain` waits. In a
maintenance window: `kubectl -n n8n delete pod -l app.kubernetes.io/component=main`
(the replacement schedules elsewhere; schedules pause for the restart), then
continue the drain.

## Troubleshooting: workers don't scale

Work through it in this order:

1. **Is the ScaledObject ready?** `kubectl -n n8n get scaledobject n8n-worker`.
   `READY False` means KEDA can't query the scaler: read the conditions with
   `kubectl -n n8n describe scaledobject n8n-worker`.
2. **KEDA operator logs:** `kubectl -n keda logs deploy/keda-operator | grep -i n8n-worker`.
   Typical lines: `error getting secret` (TriggerAuthentication), `NOAUTH` or
   `WRONGPASS` (token mismatch), `i/o timeout` (network path), TLS errors
   (`enableTLS` missing).
3. **TriggerAuthentication:** `kubectl -n n8n describe triggerauthentication n8n-redis`.
   Check that the Pod Identity association exists for `keda/keda-operator`
   (`aws eks list-pod-identity-associations --cluster-name platform-prod --namespace keda`)
   and that the operator pod was restarted after the association was created
   (credentials are injected at pod start).
4. **Network:** the operator reaches Redis through the node security group in
   the example (it has no pod security group). If the cache SG was tightened to
   the n8n pod SG only, KEDA can't poll.
5. **Wrong list key.** The most common silent failure: the scaler works,
   measures an empty list, and never activates. Compare the trigger's `listName`
   with `redis-cli --scan --pattern '*jobs*'`. A non-default `QUEUE_BULL_PREFIX`,
   cluster mode (`{bull}:...`) or worker pools (`jobs-<pool>`) all change it.
   `check_chart_policy.py` (CP009) catches the chart-side mistakes.
6. **HPA:** `kubectl -n n8n get hpa n8n-worker` shows the metric values KEDA
   reports. `<unknown>` means the metrics API call failed (KEDA metrics server).
7. **Scaled up but nothing runs:** workers not ready (`/healthz/readiness` needs
   DB connected and migrated, and Redis connected), or the CSI mount failing
   (`kubectl -n n8n describe pod` shows `FailedMount`).
