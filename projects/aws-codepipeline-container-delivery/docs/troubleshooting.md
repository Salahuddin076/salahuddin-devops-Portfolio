# Troubleshooting: secrets that inject the whole JSON blob

A common pitfall with Secrets Manager in CodeBuild and ECS. It is
presented here as a known failure mode, not as an incident from any
particular environment.

## Symptom

A secret is stored the usual way, as a JSON document with several keys:

```json
{"username": "app", "password": "example-not-real"}
```

The build or the container reads `DB_PASSWORD` and authentication fails,
even though the password in the console is correct. Debug output shows the
variable is far longer than a password, or it starts with `{`. A Docker
login fails with "unauthorized", or a database driver rejects the
credentials.

## Cause

The reference points at the *secret* and not at a *key inside it*. Without
a JSON key, CodeBuild and ECS inject the entire `SecretString`, so the
variable holds the whole JSON document, braces and all.

## Wrong and right: CodeBuild buildspec

The `env: secrets-manager` syntax is
`secret-id:json-key:version-stage:version-id`, where everything after
`secret-id` is optional. That makes the mistake easy to commit.

```yaml
# WRONG: DOCKERHUB_PASSWORD receives {"username": "...", "password": "..."}
env:
  secrets-manager:
    DOCKERHUB_PASSWORD: "container-delivery/ci/dockerhub"
```

```yaml
# RIGHT: one key per variable
env:
  secrets-manager:
    DOCKERHUB_USERNAME: "container-delivery/ci/dockerhub:username"
    DOCKERHUB_PASSWORD: "container-delivery/ci/dockerhub:password"
```

With a full ARN, the JSON key comes after the ARN's own colons:

```yaml
# RIGHT, ARN form: ...:secret:<name>-<suffix>:<json-key>
DB_PASSWORD: "arn:aws:secretsmanager:us-east-1:111122223333:secret:prod/db-AbCdEf:password"
```

## Wrong and right: ECS task definition

ECS uses the same idea with a fixed four-part suffix:
`<secret-arn>:<json-key>:<version-stage>:<version-id>`. Leave the last two
empty for the current version.

```hcl
# WRONG: DB_PASSWORD is the whole JSON document
secrets = [{ name = "DB_PASSWORD", valueFrom = aws_secretsmanager_secret.db.arn }]

# RIGHT
secrets = [{ name = "DB_PASSWORD", valueFrom = "${aws_secretsmanager_secret.db.arn}:password::" }]
```

## How this project catches it

1. **Lint at the Test stage.** `scripts/check_buildspec.py` rule **BS003**
   fails any `env: secrets-manager` value without a JSON key:

   ```text
   $ python3 scripts/check_buildspec.py tests/fixtures/bad-secret-no-json-key.yml
   FAIL tests/fixtures/bad-secret-no-json-key.yml
     [BS003] env.secrets-manager.DB_PASSWORD = 'prod/app/db' has no :json-key; the variable would receive the whole JSON secret
     [BS003] env.secrets-manager.API_KEY = 'arn:aws:secretsmanager:us-east-1:111122223333:secret:prod/api-AbCdEf' has no :json-key; the variable would receive the whole JSON secret
   0/1 buildspec file(s) passed
   ```

2. **Fail fast at runtime.** With `REQUIRE_DB_PASSWORD=true`, which the task
   definition sets, the app refuses to start when `DB_PASSWORD` looks like a
   JSON object. It logs the reason without the value, so the task fails its
   start and the deployment circuit breaker rolls back:

   ```json
   {"level": "ERROR", "logger": "app", "message": "startup_refused", "reason": "DB_PASSWORD looks like a whole JSON document; the secret reference is probably missing its :json-key suffix", ...}
   ```

   A unit test covers this path (`test_whole_json_blob_detected_without_logging_it`).

## Related mistakes

- **The key name doesn't exist in the JSON** (`:Password` vs `:password`, since
  keys are case sensitive). CodeBuild fails the build at the secrets step.
  ECS fails the task with `ResourceInitializationError`.
- **The secret has no value yet.** This module creates secrets without a
  version on purpose, so the first build or task fails until someone runs
  `put-secret-value`. See [operations](operations.md#bootstrap).
- **Plaintext under `env: variables`.** That's a different mistake but
  equally common: the value ends up in the buildspec, the repository and
  the CodeBuild console. Lint rule **BS002** blocks secret-looking names
  there.
- **Rotated secret, old value in the container.** ECS resolves `secrets` only
  at task start. Force a new deployment after rotating.
