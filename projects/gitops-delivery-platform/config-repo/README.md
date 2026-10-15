# config-repo (orders-config)

Stands in for the **config repository**: the desired state that Argo CD
reconciles. In real use this is its own repository
(`https://github.com/example-org/orders-config.git` in the manifests, a
placeholder), and `../scripts/` would live inside it.

| Path | What |
|---|---|
| `charts/orders-api/` | the Helm chart: Deployment, or Rollout + AnalysisTemplate when `rollout.enabled` |
| `envs/<env>/values.yaml` | per-environment values; `image.tag` is the only line CI and `promote.py` touch |
| `argocd/bootstrap/root-app.yaml` | app of apps, applied once by hand |
| `argocd/projects/` | AppProjects `orders-api` (no cluster-scoped kinds, sync windows) and `platform` |
| `argocd/applicationsets/orders-api.yaml` | git directory generator over `envs/*`, per-env sync policy via `templatePatch` |
| `argocd/apps/platform-base.yaml` | Application for `platform/` |
| `platform/` | namespaces (Pod Security restricted) and one ClusterSecretStore per env |
| `bootstrap/argo-cd-values.yaml` | values for the pinned `argo/argo-cd` chart (SSO, RBAC, notifications) |

Render an environment:

```bash
helm template orders-api charts/orders-api -n orders-prod -f envs/prod/values.yaml
```

The chart has no default `image.tag` on purpose; rendering without an
environment file fails, and so does any mutable tag.
