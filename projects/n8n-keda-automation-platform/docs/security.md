# Security

n8n holds the keys to everything its workflows touch: every SaaS token, API
key and database password a workflow uses is stored in its database,
encrypted with one key. So the threat model centres on three things: that
key, the database, and the ability to run arbitrary code (a Code node is a
JavaScript sandbox, and a workflow is effectively a program).

## Secrets

| Secret | Where it lives | Who can read it | How n8n gets it |
|---|---|---|---|
| `N8N_ENCRYPTION_KEY` | Secrets Manager `n8n/encryption-key`, CMK | n8n Pod Identity role | CSI file, `N8N_ENCRYPTION_KEY_FILE` |
| DB application role | Secrets Manager `n8n/db-app-credentials` (JSON) | n8n role | CSI files (jmesPath split), `DB_POSTGRESDB_USER_FILE` / `_PASSWORD_FILE` |
| Redis AUTH token | Secrets Manager `n8n/redis-auth` | n8n role, KEDA role | CSI file, `QUEUE_BULL_REDIS_PASSWORD_FILE`; KEDA via `awsSecretManager` |
| RDS master password | RDS-managed secret (`manage_master_user_password`) | admins only; neither role | not used by n8n |

- **No value in git, Helm values, the pod spec, etcd or Terraform state.** The
  three secrets are created without versions; values are put out of band. The
  ElastiCache token goes from an ephemeral read straight into the write-only
  `auth_token_wo`, so it is in neither plan nor state. RDS generates and holds
  its own master password.
- **`_FILE` is n8n's generic mechanism, verified in the image.** `@n8n/config`'s
  `readEnv` falls back to reading `<VAR>_FILE` for every variable it defines
  (trimming whitespace, with a warning). A local run with
  `N8N_ENCRYPTION_KEY_FILE` on a read-only mount started and used that key.
- **No Kubernetes Secret.** The SecretProviderClass has no `secretObjects`, and
  KEDA's TriggerAuthentication reads Secrets Manager itself
  ([ADR 0003](decisions/0003-trigger-authentication-secrets.md)). So `get secrets` RBAC in the
  namespace reveals nothing.
- **Two roles, least privilege.** The n8n role: `GetSecretValue`/`DescribeSecret`
  on three ARNs, `kms:Decrypt` only via Secrets Manager in the region. The KEDA
  role: `GetSecretValue` on the Redis token only. Both trust
  `pods.eks.amazonaws.com` with `aws:SourceAccount` and `aws:SourceArn` (this
  cluster).
- **The encryption key in memory.** n8n copies the key into
  `/home/node/.n8n/config` at start (observed locally). That directory is a
  `medium: Memory` emptyDir, so it never touches the node's disk and disappears
  with the pod. A process that can read the pod's memory or exec into it can
  read the key either way.

## Policy checks on every render

`scripts/check_chart_policy.py` runs in CI on the rendered chart (both value
files) and fails on: a literal secret-named env var (CP006), a credential-looking
value such as a URL with a password (CP006), a literal `N8N_ENCRYPTION_KEY`
(CP007), an n8n container without a key from a file or Secret (CP008), and
anything that is not queue mode (CP010). Findings mask values to their first
four characters and length.

## Pods

- Non-root (uid 1000, the image's `node` user), read-only root filesystem,
  `allowPrivilegeEscalation: false`, all capabilities dropped,
  `RuntimeDefault` seccomp. The writable paths were found by running the image
  read-only until it started: `/home/node/.n8n` (settings), `/home/node/.cache`
  (main compiles static assets there at start; without it main exits with
  `ENOENT: mkdir '/home/node/.cache'`), and `/tmp`.
- `automountServiceAccountToken: false` on the ServiceAccount and pods: n8n
  never calls the Kubernetes API. The CSI driver gets its own token from the
  kubelet for Pod Identity.
- `enableServiceLinks: false` keeps service env vars out of the environment
  workflows can read.

## Network

- **Ingress:** main and webhook accept port 5678 only from the VPC CIDR (the
  ALB's ENIs, target-type ip). Workers accept nothing.
- **Egress (all n8n pods):** cluster DNS; Postgres and Redis ports only to the
  data subnets; HTTPS to the internet *except* the VPC and `169.254.0.0/16`.
  The link-local carve-out blocks the instance metadata service and the Pod
  Identity agent: a Code node can't fetch the node role's or the pod's AWS
  credentials. ASCP (kube-system) does the Secrets Manager calls.
- **AWS layer:** RDS and ElastiCache security groups accept only security
  groups, never CIDRs: the n8n pod security group (attached through a
  `SecurityGroupPolicy` when security groups for pods are on), plus the node
  group's security group in the example so the KEDA operator can poll Redis.
  That second rule is the weak point: any pod on those nodes can reach the
  data-store ports (it still needs the AUTH token or DB password). To close it,
  give the KEDA operator its own pod security group too and drop the node
  group from `additional_client_security_group_ids`.
- **In transit:** Valkey with `transit_encryption_mode = required` (n8n
  `QUEUE_BULL_REDIS_TLS=true`, KEDA `enableTLS`), RDS with `rds.force_ssl = 1`
  (`DB_POSTGRESDB_SSL_ENABLED=true`, schema-enforced). The ALB terminates TLS
  with a TLS 1.3 policy and redirects HTTP.
- **At rest:** one CMK (rotation on) for the secrets, RDS storage, Performance
  Insights and ElastiCache.

## Workflow-level risks

- **Code nodes run JavaScript.** n8n 2.x runs them in its task runner (an
  internal child process here). Treat anyone who can edit workflows as able to
  run code with the worker's network access. The egress policy limits what
  that code can reach; it can't make editing workflows safe for untrusted users.
- **Credentials are decryptable by the platform.** Anyone with the encryption
  key and a database dump has every stored credential. Database snapshots
  (shared or exported) are therefore as sensitive as the key, so keep them on
  the CMK and out of cross-account sharing.
- **Webhooks are public by design.** Use the Webhook node's authentication
  (header or basic auth) for anything that triggers side effects, and put AWS
  WAF on the ALB for rate limiting (not in this project).
- **At-least-once execution.** A crashed worker's execution can be retried, so
  side effects need idempotency (`scripts/duplicate_job_guard.py`).

## Not covered here

SSO for the editor (an n8n Enterprise feature), audit-log shipping, WAF rules,
image signing and admission policy (see `projects/devsecops-pipeline`), and
backup restore drills for RDS.
