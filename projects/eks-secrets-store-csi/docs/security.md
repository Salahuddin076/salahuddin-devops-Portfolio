# Security

What this design protects, how, and what it leaves open. Nothing here has been deployed.
The controls are validated as code (Terraform validate, chart lint and schema, the
scanners), not observed on a cluster.

## Where a secret value exists

| Place | Holds the value? | Notes |
|---|---|---|
| Git, the image, Helm values, rendered manifests | **No** | Enforced in CI by `find_hardcoded_secrets.py` and `scan_manifests.py` |
| Terraform state and plan | **No** | No `aws_secretsmanager_secret_version`. Terraform creates empty secrets only |
| Secrets Manager | Yes | Encrypted with the CMK. Every read is a CloudTrail event |
| Node tmpfs at the pod's volume path | Yes, while a pod runs | Readable by root on the node. Gone when the pod is deleted |
| App process memory | Yes | Never logged, never returned by an endpoint |
| etcd | **No** by default | Only if `secrets.sync.enabled` (plus driver `syncSecret`) is turned on. The scanner warns (SM007) |

## Identity and least privilege

- **Per-workload role through EKS Pod Identity.** The association binds one namespace and
  ServiceAccount (`web/secure-frontend`) in one cluster to one role. The trust policy
  accepts `pods.eks.amazonaws.com` only, with `aws:SourceAccount` and `aws:SourceArn` (the
  cluster ARN) conditions, so another cluster in the account can't use the role.
  IRSA is the documented alternative ([ADR 0002](decisions/0002-pod-identity-vs-irsa.md)).
- **The policy is two actions on two ARNs.** `secretsmanager:GetSecretValue` and
  `DescribeSecret` on the exact secret ARNs (no wildcards, no `ListSecrets`), and
  `kms:Decrypt` on the CMK only with `kms:ViaService = secretsmanager.<region>.amazonaws.com`.
  The role can't call KMS directly or decrypt anything outside Secrets Manager.
- **ASCP fetches as the pod, not as the node.** The driver and provider DaemonSets have no
  Secrets Manager permissions of their own. A pod whose ServiceAccount has no association
  gets nothing, even with a SecretProviderClass naming our secret.
- **The CMK policy delegates to IAM** (account root). Grants live in IAM, where they're
  reviewed with the rest of the role.

## Why `automountServiceAccountToken: false` holds

The scanner rule SM005 requires it on the ServiceAccount and on the pod. The rule reflects
which token each component actually uses:

| Consumer | Token it uses | Affected by `automountServiceAccountToken`? |
|---|---|---|
| The app | none (no Kubernetes API, no AWS SDK) | n/a |
| CSI driver → ASCP | minted by kubelet for the pod's SA through the `CSIDriver` `tokenRequests` field, passed in the `NodePublishVolume` call | No |
| EKS Pod Identity | the webhook's projected volume `eks-pod-identity-token` (audience `pods.eks.amazonaws.com`) plus `AWS_CONTAINER_CREDENTIALS_FULL_URI` | No: injected separately from the `kube-api-access-*` volume |
| `kube-api-access-*` (the default token) | the only thing this setting controls | Yes, and nothing here needs it |

A workload that really needs the Kubernetes API can opt out with the annotation
`secrets.example.com/kube-api-token-justification: "<why>"`, which code review sees.

**Not verified on a cluster.** The `tokenRequests` path and the Pod Identity injection
match the upstream driver and the EKS documentation, but this exact combination (Pod
Identity, ASCP, automount off) hasn't been observed here. The sibling multi-region project
lists the same item as unverified.

## Network

- The app's NetworkPolicy allows ingress on 8080 from the ingress namespace and egress to
  cluster DNS. Nothing else: no AWS endpoints and no Pod Identity agent.
- **Residual risk:** the Pod Identity webhook injects credentials-endpoint env vars and a
  token into every container of a pod whose SA has an association, the app included. So
  the app *could* call Secrets Manager itself with the same role. Blocking egress to
  `169.254.170.23` stops it from exchanging the token. This depends on the VPC CNI network
  policy agent enforcing policies for link-local destinations, which hasn't been verified.
  The blast radius is the same two secrets the pod already has as files.

## The app

- Reads files only; `SECRETS_*` env vars name a directory and files, never values.
- `/healthz` returns names, `secrets_loaded`, `missing`, a 16-hex **fingerprint** and a
  rotation count. The fingerprint is a truncated SHA-256 over *all* values together, so it
  always includes the high-entropy API key: you can't confirm a guessed DB password
  against it. It tells you *that* the version changed, which is what operators and the drill
  need.
- Log lines carry names and fingerprints. A `RedactingFilter` replaces any currently loaded
  value (4+ characters) in every log record, as a backstop against a careless
  `log.error("... %s", password)`. Tests cover both, and run the real process.
- Access logs drop query strings. Responses send `Cache-Control: no-store`.
- Non-root (UID 10001), read-only root filesystem, all capabilities dropped,
  `RuntimeDefault` seccomp, no privilege escalation. The code is owned by root, so the app
  user can't modify it. `/tmp` is a 16 Mi memory `emptyDir`.

## Supply-chain and CI gates

| Gate | Catches |
|---|---|
| `find_hardcoded_secrets.py` on the project | AWS key IDs, AWS secret keys, private key headers, `password = "..."`-style literals, high-entropy strings. Output is masked. The allowlist requires a reason on every entry (two entries: the deliberate bad fixture and the detector's own tests) |
| `scan_manifests.py` on the rendered chart | Literal env secrets (by name or by value), literal `Secret` data, writable CSI mounts, mounted kube-API tokens. Warns on secret env refs and `secretObjects` |
| `values.schema.json` | `image.tag: latest`, a single replica, a relative mount path, bad file names |
| `check_workflows.py --fail-on warning` | Unpinned actions, missing `persist-credentials: false`, broad token permissions |

## Gaps (not implemented)

- **Node compromise** exposes the tmpfs files of every pod on that node. That's inherent to
  any file or env-var delivery. Mitigations: Bottlerocket or hardened AMIs, no SSH, and
  IMDSv2 with hop limit 1.
- **`kubectl exec` = read access.** Anyone who can exec into the pod can `cat
  /mnt/secrets/*`. Restrict `pods/exec` in RBAC and alert on it from the audit log.
- **The whole JSON document is mounted too** (`db-credentials`, from `objectAlias` on the
  object). ASCP writes it alongside the jmesPath files. It's the same data, so no new
  exposure.
- **No secret-specific resource policy.** A resource policy on each secret that denies
  every principal except the app role and break-glass would add a second layer. It's left
  out because it makes the bootstrap order (role before secret before policy) brittle. It's
  a sensible next step.
- **Detector coverage is small** by design (five rules, stdlib). It misses unquoted YAML
  values (`password: hunter2` in a values file) and vendor-specific token formats. Run
  gitleaks or trufflehog in the org-wide pipeline as well.
- **Rotation of the API key** has no Lambda here. It's a manual `put-secret-value` after
  reissuing the key at the provider.
