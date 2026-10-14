# ADR 0003: The app reads secrets from files and re-reads them on change

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** eks-secrets-store-csi (portfolio implementation)

## Context

The CSI driver delivers secrets as files. It can also sync them into a Kubernetes Secret
(`secretObjects`) so they can feed env vars. We had to choose how the app consumes them, and
how a rotated value reaches it.

## Decision

1. The app reads `/mnt/secrets/<name>` (`SECRETS_DIR`). It never reads secret env vars.
   Env vars carry only *where* the secrets are (`SECRETS_DIR`, `SECRETS_REQUIRED`).
2. A background watcher `stat()`s the files every `SECRETS_POLL_SECONDS`. When the inode,
   mtime or size changes, it re-reads all of them and swaps them in as one snapshot. No
   restart, no controller.
3. `secretObjects` stays off by default, with the trade-off spelled out in `values.yaml`.
4. The chart's only checksum annotation covers the SecretProviderClass *mapping*.

## Why files

- **Env vars leak.** They're visible in `/proc/<pid>/environ`, inherited by every child
  process, often included in crash reports and debug endpoints, and printed by `env` in
  support sessions.
- **Env vars don't rotate.** They're fixed at process start, so every rotation needs a
  restart, and a restart needs something to trigger it.
- **Syncing for env vars means etcd.** `secretObjects` creates a Kubernetes Secret, readable
  by anyone with `get secrets` in the namespace, kept in etcd and its backups. That's the copy
  [ADR 0001](0001-csi-driver-vs-external-secrets-operator.md) chose CSI to avoid.

## Why re-read instead of restart

| Option | Works here? |
|---|---|
| `checksum/` annotation over the secret values | **No.** Helm never sees the values (they're in Secrets Manager), so the checksum never changes on rotation |
| Reloader / restart on Secret change | Only with synced Secrets (etcd). It also restarts every pod on every rotation, a fleet-wide disruption for a credential change |
| App re-reads files | **Yes.** No extra component, no disruption, and pickup is bounded by `rotationPollInterval + SECRETS_POLL_SECONDS` |

The watcher relies on the driver's atomic `..data` symlink swap, so all files change in one
rename. Reading them back as a set means the app never pairs a new username with an old
password. `scripts/secret_rotation_drill.py` exercises exactly this against the real app.

The checksum over the SecretProviderClass mapping *is* useful: changing which secrets or
keys are mounted only takes effect on a new mount, so those changes must roll the pods.

## Consequences

- Application code must use `store.get(name)` at the point of use (or on each new
  connection), not cache the value at import time. Connection pools must be rebuilt, or
  re-authenticated, after a rotation; the `secrets rotated` log line is the hook.
- Software that only takes env vars (some third-party images) needs either a small wrapper
  that reads the files and `exec`s it (no rotation), or `secretObjects` (etcd copy). Decide
  per image and record it.
- The watcher polls; it doesn't use inotify, so it stays stdlib-only and portable.
  Ten-second `stat()` calls on tmpfs cost nothing.
