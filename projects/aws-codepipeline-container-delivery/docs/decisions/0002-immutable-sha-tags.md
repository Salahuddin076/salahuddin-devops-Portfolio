# ADR 0002: Images are tagged with the commit SHA, and tags are immutable

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** aws-codepipeline-container-delivery (portfolio implementation)

## Context

An image tag is the handle every later step uses: the deploy actions,
the rollback runbook, the approver checking what staging runs, and the
person reading `/version` during an incident. Common tagging schemes fail
in different ways:

- **`latest` (or `main`, `prod`)** moves. A task that restarts can pull a
  different image than its siblings, "roll back to the previous version"
  has no defined meaning, and an attacker or a mistaken manual push can
  replace what prod runs without a pipeline execution.
- **Build numbers** (`build-412`) are unique but say nothing about the code.
  Mapping a build number back to a commit needs CodeBuild history, which
  expires.
- **Semantic versions** need a release process this project doesn't have.
  They can also be re-pushed unless the registry forbids it.

## Decision

1. **The tag is the full 40-character commit SHA**, taken from
   `$CODEBUILD_RESOLVED_SOURCE_VERSION`. The build refuses to continue if
   the value isn't a SHA (for example, a build started manually without a
   source version).
2. **The ECR repository is `IMMUTABLE`.** A pushed tag can never point at
   another image. Rebuilding the same commit fails at push time rather than
   silently replacing the image.
3. **The same SHA is baked into the image** as `GIT_SHA` and as the OCI
   `org.opencontainers.image.revision` label, and served on `/version`.
4. **Enforced in code, not by convention:**
   - `check_buildspec.py` rule BS005 fails the Test stage if the
     `docker build -t` tag isn't derived (directly or through shell
     variables) from `CODEBUILD_RESOLVED_SOURCE_VERSION`, or if anything
     tags or pushes `latest`.
   - `make_imagedefinitions.py --require-commit-sha` refuses to write the
     deploy artifact for any tag that isn't a 40-hex SHA, and always
     refuses `latest`, `main`, `prod` and similar.
5. **Build once, promote the same artifact.** Staging and prod deploy the
   same `imagedefinitions.json`. Prod never gets a rebuild.

## Consequences

- **Rollback is precise.** "Deploy `3f9c2b1...` again" names exactly one
  image. A previous task definition revision already points at it.
- **Traceability is free.** Running task to image tag to commit to pull
  request takes no lookup table.
- **Re-running the Build stage for the same commit fails** with
  `ImageTagAlreadyExistsException`. This is deliberate. To redeploy, re-run
  the deploy stages, or roll back to an earlier execution. A future
  improvement is to skip the build when the tag already exists and its
  digest is recorded.
- **Tags are long.** That's fine for machines, and humans use the first 7-12
  characters when talking.
- **Expired images can't be redeployed.** The lifecycle policy keeps the last
  50. Older commits need a rebuild through the pipeline, which produces the
  same tag again only after the old image is gone.
- **A tag is still not a digest.** Immutability makes the tag a stable
  pointer inside this repository. Pinning the task definition to
  `@sha256:` would also protect against repository deletion and re-creation.
  The ECS deploy action accepts either. This project keeps tags for
  readability.

## Alternatives considered

- **Tag by SHA *and* move a `latest` tag for convenience.** Not possible
  with an immutable repository, and it reintroduces the ambiguity. Use
  `describe-images --query 'sort_by(imageDetails,&imagePushedAt)[-1]'` instead.
- **Mutable repository with a policy of "never re-push".** That's a
  convention, not a control. The registry setting costs nothing.
- **Short SHA (12 characters).** Collisions are unlikely at this scale, but
  the full SHA removes the question and matches what Git and GitHub
  display in full.
