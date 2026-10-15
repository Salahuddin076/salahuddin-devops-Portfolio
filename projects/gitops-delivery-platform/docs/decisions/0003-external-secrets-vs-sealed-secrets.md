# ADR 0003: External Secrets Operator instead of Sealed Secrets

- Status: accepted
- Date: 2026-10-15

## Context

GitOps puts the whole desired state in git, but secret values must not be
there in plaintext. The two common answers are encrypting secrets into git
(Sealed Secrets, SOPS) or keeping only references in git and fetching values
from a secret manager (External Secrets Operator, the Secrets Store CSI
driver).

## Decision

External Secrets Operator, with AWS Secrets Manager behind one
`ClusterSecretStore` per environment. The chart renders an `ExternalSecret`
with the remote key; the operator creates and refreshes the Kubernetes
Secret.

## Why

- **Rotation without a commit.** Rotating a database password is done in
  Secrets Manager (often automatically); ESO picks it up within
  `refreshInterval`. With Sealed Secrets every rotation is a re-seal and a PR
  per environment.
- **No long-lived decryption key in the cluster to protect and back up.**
  Sealed Secrets' controller key is the key to every secret in git; losing it
  means re-sealing everything, leaking it means every historical commit is
  readable. Here, git holds only key names.
- **Access is IAM.** Per-environment roles, assumed through EKS Pod Identity,
  limit each store to `example/orders-api/<env>/*`, and the store's
  `conditions` limit which namespace may use it. Access is audited in
  CloudTrail.
- **One source of truth for secrets shared with non-Kubernetes consumers**
  (Lambda, batch jobs) that already read Secrets Manager.

## Alternatives

- **Sealed Secrets**: fully offline and simple, a good fit when there is no
  cloud secret manager. Rejected for the rotation and key-custody reasons.
- **SOPS (with KMS) plus an Argo CD plugin**: values in git, encrypted with KMS.
  Keeps history in git, but needs a CMP plugin in the repo server and still
  a commit per rotation.
- **Secrets Store CSI driver**: mounts secrets as files without creating a
  Kubernetes Secret (the approach in projects/eks-secrets-store-csi). Good
  for file-based consumers; ESO was chosen here because the app reads env
  vars and the Secret is useful to other controllers.

## Consequences

- A Kubernetes Secret still exists in the namespace: etcd encryption with
  KMS and RBAC on Secrets still matter.
- ESO and Secrets Manager are runtime dependencies: if they are down, existing
  Secrets keep working but new namespaces or rotations wait.
- The catalog's kubeconform schema for the v1 ClusterSecretStore needs a
  one-line repair (scripts/patch_catalog_schema.py) to compile; see the README.
