# Architecture

Pull-based GitOps for one service, `orders-api`, across dev, staging and prod.
Two repositories, Argo CD in the cluster, Helm for packaging, promotion by pull
request, and an Argo Rollouts canary in prod. In this portfolio both
repositories are folders of one project (`app-repo/`, `config-repo/`); in real
use they are separate repositories with separate permissions.

## 1. Two-repo flow

The app repository builds an image and proposes a change; the config
repository is the desired state; Argo CD is the only thing that writes to the
cluster.

```mermaid
flowchart LR
  dev(["engineer"]) -- "PR, merge" --> app["app repo<br/>orders-api source + CI"]
  app -- "test, build" --> ci["CI (GitHub Actions)"]
  ci -- "push :&lt;git sha&gt;" --> reg[("ghcr.io/example-org/orders-api")]
  ci -- "PR: envs/dev image.tag" --> cfg["config repo<br/>chart + envs/* + argocd/"]
  rev(["reviewer"]) -- "approve, merge" --> cfg
  subgraph cluster["Kubernetes cluster"]
    argo["Argo CD"] -- "apply" --> ns["orders-dev / -staging / -prod"]
  end
  argo -- "poll / webhook (read-only)" --> cfg
  ns -- "pull image" --> reg
```

CI has push access to the registry and can open PRs on the config repository
through a GitHub App limited to that one repository. It has no kubeconfig, no
cloud deploy role and no network path to the API server (docs/security.md).

## 2. Promotion PR flow

`scripts/promote.py` copies the tag one step along the chain and refuses
anything else unless `--force-hotfix --reason` is given, which is then written
into the commit trailers.

```mermaid
sequenceDiagram
  autonumber
  participant CI as app CI
  participant Cfg as config repo
  participant Rev as reviewer
  participant Argo as Argo CD
  CI->>Cfg: PR "dev: deploy <sha>" (promote.py --tag <sha> --to dev)
  Rev->>Cfg: merge
  Argo->>Argo: dev auto-sync (selfHeal, prune)
  Rev->>Cfg: promote.py --from dev --to staging (PR with diff + checklist)
  Rev->>Cfg: merge
  Argo->>Argo: staging auto-sync (selfHeal, no prune)
  Rev->>Cfg: promote.py --from staging --to prod (PR)
  Rev->>Cfg: merge inside the sync window
  Rev->>Argo: manual sync of orders-api-prod
  Argo->>Argo: Rollout canary 10% -> analysis -> 50% -> analysis -> 100%
  Note over Cfg: promote.py --from dev --to prod is refused<br/>unless --force-hotfix --reason (trailer: Promotion-Hotfix: true)
```

Only the `tag:` line under `image:` changes. The rest of the values file
(comments, ordering, quoting) stays byte for byte, so the PR diff is a single
line and reviewers can trust it.

## 3. ApplicationSet fan-out

A git directory generator over `envs/*` creates one Application per
directory. The template is shared; `templatePatch` sets the sync policy per
environment. A directory the patch doesn't name (a new `envs/qa`) gets the
template default: manual sync, no prune.

```mermaid
flowchart TB
  root["Application root<br/>(app of apps, project platform)"] --> projects["AppProjects<br/>platform, orders-api"]
  root --> base["Application platform-base<br/>namespaces + ClusterSecretStores"]
  root --> appset["ApplicationSet orders-api<br/>git directories: envs/*"]
  appset --> d["orders-api-dev<br/>automated, selfHeal, prune"]
  appset --> s["orders-api-staging<br/>automated, selfHeal, no prune"]
  appset --> p["orders-api-prod<br/>manual sync, deny windows"]
  d -- "charts/orders-api + envs/dev/values.yaml" --> nd["ns orders-dev<br/>Deployment"]
  s -- "charts/orders-api + envs/staging/values.yaml" --> nsg["ns orders-staging<br/>Deployment"]
  p -- "charts/orders-api + envs/prod/values.yaml" --> np["ns orders-prod<br/>Rollout + AnalysisTemplate"]
```

The `orders-api` AppProject allows one source repository, the three
namespaces, and no cluster-scoped kinds at all (`clusterResourceWhitelist: []`).
Namespaces and ClusterSecretStores belong to the `platform` project, so the
application team can't create them, and `CreateNamespace=true` isn't needed.
`scripts/check_gitops_policy.py` expands the ApplicationSet the same way
Argo CD does and checks the result.

## 4. Canary with analysis (prod)

`rollout.enabled: true` (prod only) swaps the Deployment for an Argo Rollouts
`Rollout`. Without a traffic router, weights are approximated by the ratio of
canary to stable pods. Each analysis step runs the `orders-api-success-rate`
AnalysisTemplate: the availability SLI from
[projects/observability-sre-platform](../../observability-sre-platform/README.md)
(good = non-5xx requests, total = all requests), restricted to the canary pods
by their `rollouts-pod-template-hash`, which the ServiceMonitor copies onto
every series.

```mermaid
flowchart LR
  start(["manual sync:<br/>new image tag"]) --> w10["setWeight 10"] --> p1["pause 2m"] --> a1{"analysis<br/>success rate >= 0.99<br/>5 x 1m"}
  a1 -- "pass" --> w50["setWeight 50"] --> p2["pause 5m"] --> a2{"analysis"}
  a2 -- "pass" --> w100["setWeight 100<br/>canary becomes stable"]
  a1 -- "fail (2 bad measurements)" --> abort["abort: scale canary to 0,<br/>stable keeps 100%"]
  a2 -- "fail" --> abort
  abort --> notify["Rollout Degraded -> app health Degraded<br/>-> on-health-degraded Slack"]
```

```promql
sum(rate(http_requests_total{job="orders-api",namespace="orders-prod",
    rollouts_pod_template_hash="{{args.canary-hash}}",code!~"5.."}[2m]))
/
sum(rate(http_requests_total{job="orders-api",namespace="orders-prod",
    rollouts_pod_template_hash="{{args.canary-hash}}"}[2m]))
```

No data is a failed measurement (`len(result) > 0 && ...`), so a canary that
gets no traffic does not pass by default.

## 5. Drift and self-heal

```mermaid
flowchart LR
  edit(["kubectl edit<br/>image + label"]) --> live[("live state")]
  argo["Argo CD controller<br/>reconcile every 3m"] -- "diff desired vs live<br/>(ignoreDifferences applied)" --> live
  argo -- "OutOfSync" --> decide{"env?"}
  decide -- "dev / staging<br/>selfHeal" --> heal["re-apply git state"] --> live
  decide -- "prod<br/>manual" --> alert["stays OutOfSync<br/>visible in UI + drift report"] --> human(["engineer:<br/>sync or PR"])
```

`ignoreDifferences` on `/spec/replicas` for Deployments and Rollouts, with
`RespectIgnoreDifferences=true`, keeps the HPA's replica count from showing up
as drift or being reset by a sync. The chart also leaves `spec.replicas` out
when the HPA is on. `scripts/drift_report.py` reproduces the comparison
offline, on a `kubectl get -o json` export, for audits and for prod where
nothing heals automatically.

## Components and versions

| Component | Version referenced | Where |
|---|---|---|
| Argo CD | chart `argo/argo-cd` 10.10.3 (app v3.5.5) | `config-repo/bootstrap/argo-cd-values.yaml`, docs/operations.md |
| Argo Rollouts | chart `argo/argo-rollouts` 2.43.7 (app v1.10.1) | docs/operations.md |
| External Secrets Operator | chart `external-secrets` 2.12.0, API `external-secrets.io/v1` | `platform/`, chart `externalsecret.yaml` |
| Prometheus Operator | `monitoring.coreos.com/v1` ServiceMonitor | chart `servicemonitor.yaml` |
| Kubernetes schemas | 1.34.0 | kubeconform |

The versions are pinned in the docs and the bootstrap values; nothing here was
installed into a cluster (see Limitations in the README).
