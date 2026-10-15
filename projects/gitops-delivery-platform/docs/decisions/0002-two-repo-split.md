# ADR 0002: Separate application and config repositories

- Status: accepted
- Date: 2026-10-15

## Context

The desired state (chart, per-environment values, Argo CD manifests) could
live next to the application code or in its own repository.

## Decision

Two repositories:

- **app repo**: source, tests, Dockerfile, CI that builds and pushes an image
  tagged with the commit SHA.
- **config repo**: the Helm chart, `envs/<env>/values.yaml`, and the Argo CD
  AppProjects, ApplicationSet and bootstrap.

CI connects them with a pull request that changes one line
(`envs/dev/values.yaml` `image.tag`). Promotions are pull requests in the
config repo only. In this portfolio both are folders of one project; the
split is documented, not enforced.

## Why

- **Different change rates and reviewers.** Application code changes many
  times a day; promotions and platform settings need platform or on-call
  review. Branch protection and CODEOWNERS can differ per repository.
- **No CI loops.** Argo CD watching the app repo would see every code commit;
  CI committing tags back into the app repo would trigger itself.
- **Least privilege.** The bot that opens bump PRs can write to the config
  repo and nothing else. Argo CD reads only the config repo.
- **One place for the state of an environment.** `git log envs/prod` is the
  full deployment history of prod.

## Alternatives

- **Monorepo with path filters**: fewer repositories, but CI and Argo CD
  permissions become path-based and harder to reason about.
- **Argo CD Image Updater** writing tags back to git: less glue, but it
  promotes by polling the registry and hides the review step that the PR
  gives us. A reasonable option for dev only.

## Consequences

- A code change takes two merges to reach dev (app PR, then bump PR). The
  bump PR can be auto-merged for dev when its checks pass.
- The chart version and the app version move independently; the chart lives
  with the environments that use it.
