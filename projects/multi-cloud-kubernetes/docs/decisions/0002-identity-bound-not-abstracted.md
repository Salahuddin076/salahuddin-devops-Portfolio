# 0002: Bind to each cloud's native identity; never abstract it away

## Status

Accepted.

## Context

A common "multi-cloud" instinct is to build an abstraction layer that hides
IRSA/Entra Workload ID/GKE Workload Identity behind one interface (e.g. a
custom operator, or a third-party identity broker) so application teams
write one manifest and never think about which cloud they're on. That
abstraction has a real cost: it is one more thing to operate, one more thing
that can be wrong in a way neither `terraform validate` nor `helm
template`/`kubeconform` can catch (a subject-string mismatch between the
Terraform side and the Kubernetes side fails at token-exchange time with an
opaque, cloud-specific error -- see each sibling project's README "Lessons"
section), and it does not remove the underlying protocol difference, it just
moves it somewhere less visible.

## Decision

`helm/portable-service` does not abstract workload identity. Each overlay
sets the literal, cloud-native ServiceAccount annotation
(`eks.amazonaws.com/role-arn`, `azure.workload.identity/client-id`,
`iam.gke.io/gcp-service-account`) for that cloud's actual mechanism. The
portability this project claims is narrower and more honest: the same
chart, the same ServiceAccount *name*, the same deployment model (one
ArgoCD ApplicationSet) -- not a unified identity API.

## Consequences

- `tests/test_helm_static.py` asserts each overlay's annotation key matches
  that cloud's real convention, not a synthetic abstraction layer's own key.
- Nothing in this project claims cross-cloud failover or data replication --
  the three clusters are independently highly available, not a single
  logical system. `docs/architecture.md` states this explicitly, matching
  the website's "reference" (not "production case study") evidence label for
  this project.
- Abstracting only the genuinely cheap parts (the container image, the Helm
  chart's structure, the deployment pipeline) and leaving the genuinely
  different parts (identity, ingress, storage, cost/upgrade policy) visible
  is the actual lesson of this project -- see `docs/comparison.yaml`.
