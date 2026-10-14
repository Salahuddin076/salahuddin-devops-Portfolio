# ADR 0003: KEDA reads the Redis token from Secrets Manager with its own Pod Identity

- Status: accepted
- Date: 2026-10-14

## Context

The ElastiCache replication group requires an AUTH token, and KEDA's operator
must present it to poll the Bull lists. n8n's pods already get the token as a
CSI file. KEDA's `TriggerAuthentication` can't read a CSI mount: it takes a
Kubernetes Secret (`secretTargetRef`), an env var of the target pod (`env`),
or a provider it calls itself, such as `awsSecretManager`.

## Options

**A. Sync a Kubernetes Secret with the CSI driver** (`secretObjects` in the
SecretProviderClass) and point `secretTargetRef` at it.

- Pros: one fetch path, a familiar pattern, no extra IAM role.
- Cons: the token lands in etcd and is readable by anyone with `get secrets`
  in the namespace. Worse for this design, the CSI driver creates the synced
  Secret only while some pod mounts the volume and deletes it when none does.
  It survives here only because main always runs, so scaling the workers from
  zero would quietly depend on main being up, and on the add-on running with
  `syncSecret.enabled`.

**B. KEDA's `awsSecretManager` provider with `podIdentity.provider: aws`**,
operator identity (`identityOwner: keda`).

- Pros: no Kubernetes Secret anywhere; the scaler works whether or not any n8n
  pod is running; the operator's role can read exactly one secret; rotation
  needs no restart of KEDA.
- Cons: a second Pod Identity association and IAM role (Terraform, small), and
  the KEDA operator now calls Secrets Manager (cost negligible). It needs KEDA
  2.15+ for the `aws` pod identity provider.

**C. `env` from the worker pod.** Not available: n8n's pods carry a file path,
not the value, and the target has zero pods when it matters most.

## Decision

Option B. The `TriggerAuthentication` uses `awsSecretManager` with
`podIdentity: {provider: aws, identityOwner: keda}`, mapping secret
`n8n/redis-auth` to the scaler's `password` parameter. Terraform creates the
`keda/keda-operator` association with a role that has `GetSecretValue` on
that secret and `kms:Decrypt` only through Secrets Manager.

## Consequences

- No synced Secret: the chart renders no `Secret` and no `secretObjects` (a
  test asserts both).
- Two principals can read the token (the n8n role and the KEDA role), each
  with a one-line reason.
- If the association is created after the operator pod started, the operator
  has no credentials until it restarts ([troubleshooting](../operations.md#troubleshooting-workers-dont-scale)).
- Unverified until run: that `identityOwner: keda` is honoured for the `aws`
  provider exactly as the KEDA docs describe. The field names are validated
  against the CRD schema (kubeconform, community catalog), not against a live
  operator.
