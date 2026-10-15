# ADR 0001: Pull-based GitOps with Argo CD

- Status: accepted
- Date: 2026-10-15

## Context

Several platform services are deployed to dev, staging and prod. Today a CI
job with a kubeconfig runs `helm upgrade` at the end of the pipeline (push
model). That gives every CI run cluster-admin-like power, the cluster's real
state is whatever the last job did, and manual `kubectl edit` changes go
unnoticed until they cause an incident.

## Decision

Use a pull model: Argo CD runs in the cluster, watches a config repository
and reconciles the cluster to it. CI builds images and proposes changes as
pull requests; it never talks to the cluster.

- dev and staging sync automatically with self-heal; prod syncs by hand
  inside sync windows.
- The ApplicationSet controller generates one Application per environment
  directory, so a new environment is a new folder, not new pipeline code.
- Drift is visible (OutOfSync) everywhere and corrected automatically where
  that's safe.

## Alternatives

- **Push from CI (status quo)**: simplest, but it needs cluster credentials
  in CI and has no drift detection.
- **Flux**: the same pull model. Argo CD was chosen for its UI (which
  application teams use to see sync and health), AppProjects as a
  multi-team boundary, sync windows, and first-class Argo Rollouts
  integration. Flux would be equally valid with Flagger for canaries.

## Consequences

- Cluster credentials leave CI completely (docs/security.md).
- Git history is the deployment audit log, and rollback is `git revert`.
- Argo CD becomes critical infrastructure: it needs HA, backups of its
  configuration (which is in git anyway) and its own upgrade process.
- Deploys are asynchronous: a merged PR is not a finished deploy. CI can no
  longer report "deployed"; Argo CD notifications and health do.
