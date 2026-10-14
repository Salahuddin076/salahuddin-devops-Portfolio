# ADR 0001: Secrets Store CSI Driver (ASCP) over External Secrets Operator

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** eks-secrets-store-csi (portfolio implementation)

## Context

The app needs a DB credential and an API key from AWS Secrets Manager on EKS, rotated
without a redeploy, and nothing in git, images or Helm values. Two mainstream ways to get
Secrets Manager values into pods:

1. **Secrets Store CSI Driver + AWS provider (ASCP).** A CSI volume. At mount time, the
   provider fetches the secrets *as the pod's own IAM identity* and writes them to a tmpfs
   inside the pod. Optional `secretObjects` also copies them into a Kubernetes Secret.
   Available as the EKS add-on `aws-secrets-store-csi-driver-provider`.
2. **External Secrets Operator (ESO).** A controller that reconciles `ExternalSecret`
   resources into Kubernetes `Secret` objects, using a `SecretStore` identity. Pods consume
   ordinary Secrets (env or volume).

## Decision

Use the CSI driver with ASCP, installed as the EKS managed add-on, with `secretObjects` off.

## Why

| Concern | CSI + ASCP | ESO |
|---|---|---|
| Value in etcd | No (unless `secretObjects`) | Always: that's its output |
| Whose IAM identity reads the secret | The consuming pod's (Pod Identity per ServiceAccount) | The controller's, or one per `SecretStore`. Any pod that can read the namespace's Secrets gets the value |
| Pod starts without its secret | Can't: `FailedMount` blocks the container | Can, if the Secret is missing or stale. Ordering is the app's problem |
| Rotation reaches the pod | Driver rewrites the files (`rotationPollInterval`); the app re-reads | Controller updates the Secret (`refreshInterval`); kubelet syncs volume Secrets, but env vars need a restart (Reloader) |
| API calls | Per pod per secret per poll ([cost](../cost.md)) | Per `ExternalSecret` per refresh: cheaper at high replica counts |
| Install and upgrades | EKS managed add-on | Helm chart you operate. CRDs and webhook are yours to upgrade |
| Templating, generators, push to other stores | No | Yes: rich templating, PushSecret, many providers |

What tipped it: **identity per workload** and **no etcd copy**. With ESO, read access to
Secrets in a namespace (a common RBAC grant) becomes read access to the database password.
With CSI, the only readers are the pods whose ServiceAccount is bound to the role.

## Consequences

- The app must read files ([ADR 0003](0003-files-not-env-vars.md)). Software that only takes
  env vars needs `secretObjects`, and gets ESO's etcd trade-off without its features.
- Polling cost scales with replicas. It's fine for this workload. Revisit above a few
  hundred pods per secret.
- Each node runs two more DaemonSets (driver and provider). They're small, but they need
  tolerations for every tainted node group that runs consumers.
- **When ESO would win:** many small services that all take env vars, secrets that need
  templating (connection strings assembled from parts), or a multi-cloud estate with one
  operator for every store.
