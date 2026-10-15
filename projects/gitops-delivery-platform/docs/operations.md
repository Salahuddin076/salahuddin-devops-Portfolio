# Operations

Runbook-style notes for the platform. Hostnames, groups and repositories are
placeholders (`example.com`, `example-org`).

## Bootstrapping Argo CD

Done once per cluster by a platform engineer with cluster-admin. After this,
every change goes through git.

1. Install the controllers with pinned chart versions:

   ```bash
   helm repo add argo https://argoproj.github.io/argo-helm
   helm repo add external-secrets https://charts.external-secrets.io
   helm upgrade --install argocd argo/argo-cd --version 10.10.3 \
     --namespace argocd --create-namespace -f config-repo/bootstrap/argo-cd-values.yaml
   helm upgrade --install argo-rollouts argo/argo-rollouts --version 2.43.7 \
     --namespace argo-rollouts --create-namespace
   helm upgrade --install external-secrets external-secrets/external-secrets --version 2.12.0 \
     --namespace external-secrets --create-namespace
   ```

   In a mature setup these three releases are themselves Argo CD
   Applications in the `platform` project (Argo CD manages itself), and this
   manual step is only for the very first install.

2. Give the External Secrets controller its AWS identity through EKS Pod
   Identity (an association for `external-secrets/external-secrets` to a role
   that may only `sts:AssumeRole` into the three `example-eso-orders-<env>`
   roles). See docs/security.md.

3. Register the config repository read-only (a deploy key or a GitHub App
   with `contents: read`), then apply the platform project and the root app:

   ```bash
   kubectl apply -n argocd -f config-repo/argocd/projects/platform.yaml
   kubectl apply -n argocd -f config-repo/argocd/bootstrap/root-app.yaml
   ```

   `root` is the app of apps: it syncs everything under `argocd/` except
   `bootstrap/`: both AppProjects, the `platform-base` Application (namespaces
   and ClusterSecretStores) and the `orders-api` ApplicationSet, which creates
   one Application per `envs/*` directory.

4. Check: `argocd app list` shows `root`, `platform-base`,
   `orders-api-dev`, `orders-api-staging` (both syncing on their own) and
   `orders-api-prod` (OutOfSync until someone syncs it).

5. Disable the local admin (`admin.enabled: false` is already in the values)
   once SSO works.

## Promoting

CI puts every new build into dev by PR. Moving it further is a PR too:

```bash
python3 scripts/promote.py --from dev --to staging --commit --branch promote/staging-<sha12> \
  --config-repo <checkout of the config repo> --pr-body /tmp/pr.md
git push origin promote/staging-<sha12>   # then open the PR with /tmp/pr.md as the body
```

- The tag must be immutable: a 40-char git SHA, or `<semver>-<7..40 hex>`.
  `latest`, branch names and bare semver are refused; the chart refuses them
  again at render time.
- Only the next environment is allowed (dev to staging, staging to prod).
- The PR body has the old and new tag, the one-line diff and a checklist.
- staging syncs on merge. prod needs a manual sync inside the sync window:
  `argocd app sync orders-api-prod`, then watch the canary with
  `kubectl argo rollouts get rollout orders-api -n orders-prod --watch`.

## Emergency hotfix

When a fix must reach prod without waiting for staging:

```bash
python3 scripts/promote.py --from dev --to prod --force-hotfix \
  --reason "INC-1234: checkout timeouts" --commit --branch hotfix/prod-<sha12>
```

The commit carries `Promotion-Hotfix: true` and `Hotfix-Reason: ...` as git
trailers, so hotfixes can be listed later with
`git log --format='%h %(trailers:key=Hotfix-Reason,valueonly)' --grep='Promotion-Hotfix: true'`.
It still needs an approving review and a merge. If it is outside business
hours, see "Sync windows" below for the override. Promote the same tag into
staging afterwards so the chain is consistent again.

## Rollback

Two different tools for two different situations:

| Situation | Action | Why |
|---|---|---|
| Canary is failing right now | `kubectl argo rollouts abort orders-api -n orders-prod` | Stops the rollout and scales the canary to zero; stable pods keep serving. The analysis does this automatically when it fails. |
| A promoted version is bad after it went to 100% | `git revert <promotion commit>` in the config repo, PR, merge, sync | Git stays the source of truth. The revert is the new desired state, and it rolls out through the same canary. |
| Need the previous ReplicaSet immediately, git can follow | `kubectl argo rollouts undo orders-api -n orders-prod`, then the git revert | Fastest path, but it makes the live state differ from git: prod shows OutOfSync until the revert lands. Never leave it there. |

`argocd app rollback` to an earlier sync also works but has the same
problem as `undo` (live differs from git), and Argo CD refuses it while
automated sync is enabled. It is not used for dev and staging, where
self-heal would undo it anyway: revert in git.

## Handling drift

- **dev and staging** have `selfHeal: true`: a manual change is reverted at
  the next reconcile (about 3 minutes). If someone needs a temporary change
  there, it goes through git.
- **prod** is manual: drift shows as OutOfSync in the UI and in the
  Slack notification for health problems. Decide whether to keep it (make a
  PR so git matches) or discard it (sync).
- For audits, or when Argo CD itself is suspect, compare an export with the
  rendered chart:

  ```bash
  helm template orders-api config-repo/charts/orders-api -n orders-prod -f config-repo/envs/prod/values.yaml > desired.yaml
  kubectl get deploy,rollout,svc,ingress,hpa,pdb,networkpolicy,externalsecret,servicemonitor,sa \
    -n orders-prod -o json > live.json
  python3 scripts/drift_report.py --desired desired.yaml --live live.json \
    --app config-repo/argocd/applicationsets/orders-api.yaml
  ```

  It exits 1 on drift and lists each field: `~` changed, `+` only in live
  (labels, annotations, extra containers), `-` missing in live. Replica counts
  on HPA targets, `status`, `managedFields` and the bookkeeping annotations
  are ignored, the same as the Applications' `ignoreDifferences`.

## Sync windows

The `orders-api` AppProject has two deny windows for `orders-api-prod`
(UTC): weeknights 17:00 to 08:00 and the weekend, Saturday 00:00 to Monday
08:00. `manualSync: false`, so even a manual sync is refused outside 08:00 to
17:00 Monday to Friday. `check_gitops_policy.py` (GP007) simulates a week
minute by minute and fails if any minute outside business hours is not
covered.

Break-glass override, for an incident out of hours:

1. Open a PR on the config repo that sets `manualSync: true` on the active
   window (or temporarily removes it), with the incident number in the title.
   An on-call platform engineer approves; the root app syncs it in about 3 minutes.
2. Sync `orders-api-prod` by hand.
3. Revert the window change the next working day. The policy check fails the
   config repo's CI while `manualSync: true` is set (GP007), which keeps the
   override from becoming permanent unnoticed.

`argocd proj windows enable-manual-sync orders-api <id>` does the same thing
from the CLI, but `root` would revert it at its next sync (it has
`selfHeal: true`), so the PR is the method that sticks and leaves an audit trail.

## Notifications

Every environment Application subscribes `on-sync-failed` and
`on-health-degraded` to the Slack channel `orders-alerts` (placeholder) via
annotations. The triggers and message templates are in the Argo CD values;
the Slack token comes from `argocd-notifications-secret`, which an
ExternalSecret fills, never from git.
