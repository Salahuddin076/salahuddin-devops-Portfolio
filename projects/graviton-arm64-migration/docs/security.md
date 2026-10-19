# Security

## Image scanning per architecture, not per tag

The two platforms behind one manifest-list tag share the application layer
but not necessarily the base-OS layer. `terraform/modules/ecr-multiarch`
turns on `scan_on_push` so every pushed platform manifest is scanned
independently, and `scripts/compatibility_check.py` (rules GC003-GC005)
refuses to let a service past the `canary` rollout stage unless **both**
platform scans show `status: pass` with no outstanding critical/high
findings. See [compatibility-checklist.md](compatibility-checklist.md#4-image-scanning-per-architecture).

## Base images pinned by digest, per platform

`base_image` in the compatibility manifest must be `name@sha256:<64 hex>`
(rule GC002), and that digest is the platform-specific one — the digest you
get back from `docker buildx imagetools inspect <tag>` for that one
platform, not the manifest-list digest. Pinning by tag lets the base image
move out from under a service between when it passed compatibility testing
and when it's promoted; pinning by digest makes "what's actually running"
answerable without trusting the registry's current state of a mutable tag.

## IAM: node role scope, not image scope

`terraform/modules/eks-arch-node-group` creates one node IAM role per pool
by default (`node_role_arn = null`), attached to
`AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly` and
`AmazonEKS_CNI_Policy`. `ecr_repository_arns` lets an account that wants
tighter scope replace the account-wide ECR read policy with an inline policy
naming only the repositories that pool needs to pull from — useful once a
migration has several services each with their own repository and a pool
shouldn't be able to pull images it has no business running.

## ECR: immutable tags

`image_tag_mutability = "IMMUTABLE"` by default. Once a tag is pushed as a
manifest list, it cannot be silently repointed at a different pair of
platform images — the thing that makes "rollback = remove the ARM64
affinity" safe in the first place (see
[architecture.md](architecture.md#rollback)) depends on the tag a rolled-back
Deployment points at still meaning exactly what it meant before the
rollback.

## Pod-level hardening

`helm/multiarch-app` runs every pod non-root (`runAsUser: 10001`,
`runAsNonRoot: true`), with a read-only root filesystem, all Linux
capabilities dropped, `allowPrivilegeEscalation: false`, the default seccomp
profile, and `automountServiceAccountToken: false` (the app makes no
Kubernetes API calls). This is identical across both the stable and canary
Deployments — architecture never changes the pod's trust boundary, only
where it's scheduled.

## Native vs emulated builds and supply-chain risk

A QEMU-emulated build pulls in the emulator itself as a build-time
dependency and runs the target architecture's code under an interpreter
that isn't part of the production runtime path. `compatibility-checklist.md`
treats native build agents as the default (ADR 0001) partly for correctness
and partly because an emulated build's toolchain is a larger, less-audited
surface than a native one for no additional capability.

## What's not covered here

This project doesn't include a cluster's RBAC, network policy, or secrets
handling — see `projects/eks-secrets-store-csi` and
`projects/aws-multi-region-eks-dr` for those. The scope here is strictly the
architecture-migration surface: image provenance across two platforms, and
the IAM/ECR boundary around the node pools that run them.
