# Security

## CI has no cluster credentials

The point of pull-based delivery: the thing that builds code cannot change the
cluster.

- The app CI (`app-repo/.github/workflows/ci.yml`) has `contents: read` at the
  top level. Only the build job gets `packages: write` to push the image.
- The bump job uses a token from a GitHub App installed only on the config
  repository, with `contents: write` and `pull-requests: write` there. It
  opens a PR; it cannot merge (branch protection requires review), and it
  cannot touch other repositories.
- There is no kubeconfig, cloud deploy role or OIDC trust to a cluster in any
  workflow. A compromised CI run can push an image and propose a change,
  both of which need a human to go further.
- All actions are pinned to commit SHAs with a version comment, checkouts set
  `persist-credentials: false`, and both workflows pass the repo's
  `check_workflows.py --fail-on warning`.
- Images are tagged with the full git SHA and never overwritten. The chart's
  schema and template, `promote.py` and the policy check all reject `latest`
  and other mutable tags. Signing with cosign and admission verification
  (Kyverno or Sigstore policy-controller) are the next steps; they are not
  part of this implementation.

## Argo CD's access

- Argo CD reads the config repository with a read-only credential. Nothing in
  the cluster can write to git.
- It reaches the API server from inside the cluster, so no API endpoint has to
  be exposed to CI.

## AppProject boundaries

| Project | Source repos | Destinations | Cluster-scoped kinds | Namespaced kinds |
|---|---|---|---|---|
| `orders-api` | the config repo | `orders-dev`, `orders-staging`, `orders-prod` on the local cluster | none (`[]`) | the 11 kinds the chart renders |
| `platform` | the config repo | `argocd`, `external-secrets` | `Namespace`, `ClusterSecretStore` | `AppProject`, `Application`, `ApplicationSet` |

So the application team's project cannot create a ClusterRole, a webhook, a
CRD or a namespace, cannot deploy into `kube-system`, and cannot pull manifests
from another repository, even if someone adds them to the chart. A Secret is
not on the whitelist either: secrets come from External Secrets only.
`check_gitops_policy.py` enforces the cluster-scoped and destination rules
(GP003, GP004) in CI.

## SSO and RBAC

- Local `admin` is disabled after bootstrap; people sign in through OIDC
  (placeholder issuer `https://sso.example.com/realms/engineering`) with a
  `groups` claim.
- `policy.default` is empty: a signed-in user with no group mapping sees
  nothing.
- Global roles: `example-org:platform-admins` is admin,
  `example-org:engineering` read-only.
- Project roles in the `orders-api` AppProject: `deployer`
  (`example-org:orders-maintainers`) may get, sync and run Rollout actions
  (promote, abort) on orders-api apps; `viewer` may only read. Prod syncs
  are still limited by the sync windows.
- `exec.enabled: false`: no web terminal into pods.

## Secrets: External Secrets with EKS Pod Identity

- No secret value is in git, the chart or any values file. The chart renders
  an `ExternalSecret` that references a remote key
  (`example/orders-api/<env>/database`); the operator creates the Kubernetes
  Secret `orders-api-secrets`, which the pod reads with `envFrom`.
- One `ClusterSecretStore` per environment. Each assumes its own IAM role
  (`example-eso-orders-<env>`, policy limited to
  `secretsmanager:GetSecretValue` on `example/orders-api/<env>/*`), and its
  `conditions` accept ExternalSecrets only from that environment's
  namespace. A dev manifest can't read a prod secret even by naming the prod
  store.
- The controller's base identity comes from **EKS Pod Identity**: an
  association binds the `external-secrets` service account to a role whose
  only permission is `sts:AssumeRole` (with `sts:TagSession`) into the three
  per-environment roles. No static keys, no IRSA annotations to manage.
- The ADR (decisions/0003) explains why External Secrets over Sealed Secrets.

## Workload hardening

Enforced by the chart and checked by the rendered-chart tests:
`runAsNonRoot` with UID 10001 (matching the Dockerfile), read-only root
filesystem with an `emptyDir` for `/tmp`, no privilege escalation, all
capabilities dropped, `RuntimeDefault` seccomp, no service account token
mounted, CPU and memory requests and a memory limit, probes, a
PodDisruptionBudget, and a NetworkPolicy that admits traffic only from the
ingress controller and monitoring namespaces and allows egress only to DNS
and the database CIDR. Namespaces enforce Pod Security `restricted`.
