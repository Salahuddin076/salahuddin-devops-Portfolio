# Operations

Commands use the defaults: namespace `web`, release and ServiceAccount `secure-frontend`,
region `us-east-1`, account `123456789012`. None of this has run against a real account.

## Before the first apply

1. **Check the add-on's configuration schema** for the version you pin. The module nests
   driver settings under `secrets-store-csi-driver`. `syncSecret.enabled` under that key is
   documented. The rotation keys are assumed to follow the upstream chart:

   ```bash
   aws eks describe-addon-versions --addon-name aws-secrets-store-csi-driver-provider \
     --kubernetes-version 1.34 --query 'addons[0].addonVersions[].addonVersion'
   aws eks describe-addon-configuration --addon-name aws-secrets-store-csi-driver-provider \
     --addon-version <version> --query configurationSchema --output text | python3 -m json.tool
   ```

   If `enableSecretRotation` or `rotationPollInterval` sit elsewhere, change
   `local.csi_addon_configuration` in `addons.tf`. EKS rejects unknown keys when the add-on is
   created, so a mismatch fails the apply instead of being silently ignored.
2. **Pod Identity agent.** `kubectl -n kube-system get ds eks-pod-identity-agent`. If it's
   missing and nothing else manages it, set `manage_pod_identity_agent_addon = true`.
3. **Remove any self-managed install** of the driver or ASCP (Helm releases
   `csi-secrets-store` / `secrets-provider-aws`). Two drivers registering
   `secrets-store.csi.k8s.io` conflict. The add-on uses `resolve_conflicts_on_create = "OVERWRITE"`.

## Bootstrap

```bash
cd terraform/examples/basic
terraform init && terraform apply        # owner only; this repo only validates

# Values go in out of band, from files, so they stay out of shell history and Terraform state.
umask 077
python3 - > /dev/shm/db.json <<'EOF'
import json, getpass
print(json.dumps({"username": "app", "password": getpass.getpass("DB password: "),
                  "host": "orders.cluster-example.us-east-1.rds.amazonaws.com"}))
EOF
aws secretsmanager put-secret-value --secret-id secure-frontend/dev/db-credentials \
  --secret-string file:///dev/shm/db.json && shred -u /dev/shm/db.json
read -rs API_KEY && printf '%s' "$API_KEY" > /dev/shm/api-key && unset API_KEY   # builtin: not in ps
aws secretsmanager put-secret-value --secret-id secure-frontend/dev/api-key \
  --secret-string "file:///dev/shm/api-key" && shred -u /dev/shm/api-key

helm upgrade --install secure-frontend helm/secure-frontend -n web --create-namespace \
  --set secrets.db.secretName=secure-frontend/dev/db-credentials \
  --set secrets.apiKey.secretName=secure-frontend/dev/api-key
```

`terraform output helm_values` prints the values that must agree with the stack. The
ServiceAccount name and namespace must match the Pod Identity association exactly.

Enable managed rotation only after the first value exists: set `rotation_lambda_arn` and
apply again. The module sets `rotate_immediately = false`, so turning rotation on doesn't
rotate on the spot. Run `aws secretsmanager rotate-secret --secret-id ...` once by hand and
watch the pods pick it up (`/healthz` `version` changes, `rotations` goes up).

## Rolling out to an existing app that uses env vars

The goal is to switch the source without a window where the app has no credentials, then
treat the old values as exposed.

1. **Inventory.** Render the current chart and run the scanner on it. Every SM001, SM003
   and SM006 finding is a secret to migrate:
   `helm template old-release ./chart | python3 scripts/scan_manifests.py -`.
2. **Create the secrets** (Terraform) and put the *current* values (bootstrap above), so
   behaviour doesn't change on the switch.
3. **Teach the app to read files.** Read `SECRETS_DIR/<name>` first and fall back to the env
   var during the migration. Log which source was used, never the value. Re-read on change
   (as in `app/server.py`), or at least on every new connection.
4. **Deploy the chart change.** Add the `SecretProviderClass`, the CSI volume and the Pod
   Identity association, and keep the env vars for one release. Check
   `kubectl -n web get secretproviderclasspodstatuses` and the app's "loaded from file" log.
5. **Remove the env vars and the old Kubernetes Secret.** The scanner must now be clean.
   Delete the Secret: `kubectl -n web delete secret <old>`.
6. **Rotate every migrated value.** The old values lived in git history, etcd and possibly
   images. Moving them doesn't make them secret again; rotating does.
7. **Add the CI gates** (`scan_manifests.py --fail-on error` on the rendered chart,
   `find_hardcoded_secrets.py` on the repository) so the old pattern can't come back.

## Incident: a credential was exposed

Order matters. **Contain first, investigate second, clean up last.** History rewriting
feels urgent, but it doesn't help: the value was already readable by everyone who
cloned, forked, or scanned the repository.

### 1. Revoke or rotate (minutes)

| What leaked | Action |
|---|---|
| IAM access key (`AKIA...`) | `aws iam update-access-key --access-key-id AKIA... --status Inactive --user-name <user>`. Create the replacement, then delete the old key. If the user is unknown: `aws iam get-access-key-last-used --access-key-id AKIA...` |
| DB credential in Secrets Manager | `aws secretsmanager rotate-secret --secret-id secure-frontend/dev/db-credentials` (with a rotation Lambda), or put a new value and change the DB password. Pods pick it up within `rotationPollInterval + SECRETS_POLL_SECONDS` |
| Third-party API key | Revoke it in the provider's console, put the new key with `put-secret-value`, and confirm `/healthz` `version` changed on every pod |
| A Kubernetes Secret (synced or legacy) | Rotate the source value. Then delete the Secret, so the driver recreates it (synced) or nothing does (legacy) |

To cut access at once, add an explicit deny to the role while you rotate. It's the
fastest lever that doesn't depend on the leaked value:
`aws iam put-role-policy --role-name secure-frontend-dev-secrets-reader --policy-name incident-deny --policy-document file://deny-all.json`.
Pods fail closed on their next fetch and keep the files they already have.

### 2. Find usage (hours)

```bash
# Everything done with a leaked IAM key (90 days of management events).
aws cloudtrail lookup-events --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=AKIA... \
  --start-time 2026-10-01T00:00:00Z --query 'Events[].[EventTime,EventName,Username]' --output table

# Who read the secret, and from where. Expect only the Pod Identity role sessions.
aws cloudtrail lookup-events --lookup-attributes AttributeKey=ResourceName,AttributeValue=<secret ARN> \
  --query 'Events[].[EventTime,EventName,Username]' --output table
```

For anything older than 90 days, or data events, query the organization trail in Athena.
Filter on `eventsource = 'secretsmanager.amazonaws.com'` and `eventname = 'GetSecretValue'`,
and group by `useridentity.arn` and `sourceipaddress`. A session that isn't
`secure-frontend-*-secrets-reader/eks-...` deserves a closer look. Check the database's own
audit log for logins from unexpected addresses.

### 3. Remove from history (after rotation)

```bash
python3 scripts/find_hardcoded_secrets.py .            # confirm what and where
git filter-repo --replace-text expressions.txt          # literal==>***REMOVED***
git push --force-with-lease --all && git push --force-with-lease --tags
```

Then ask the hosting provider to purge cached views and pull-request refs, tell everyone to
re-clone, and add the pattern to CI so it fails next time. Record the timeline:
detection, revocation, rotation, last malicious use (if any).

## Troubleshooting

Start with the pod's events, then the driver and provider logs on that pod's node:

```bash
kubectl -n web describe pod -l app.kubernetes.io/name=secure-frontend | sed -n '/Events/,$p'
NODE=$(kubectl -n web get pod -l app.kubernetes.io/name=secure-frontend -o jsonpath='{.items[0].spec.nodeName}')
kubectl -n kube-system get pods -o wide --field-selector spec.nodeName=$NODE | grep -Ei 'secrets-store|provider'
kubectl -n kube-system logs <driver-pod-on-node> -c secrets-store
kubectl -n kube-system logs <provider-pod-on-node>
```

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod stuck in `ContainerCreating`, event `FailedMount ... rpc error: ... failed to mount secrets store objects for pod web/...` | Generic wrapper. The real reason follows in the same message | Read the rest of the message, then the rows below |
| `FailedMount ... driver name secrets-store.csi.k8s.io not found in the list of registered CSI drivers` | Driver DaemonSet not on that node (taints, add-on degraded) | `aws eks describe-addon --addon-name aws-secrets-store-csi-driver-provider --cluster-name ...`. Check the DaemonSet's tolerations against the node's taints |
| `AccessDeniedException ... is not authorized to perform: secretsmanager:GetSecretValue` | Association doesn't match (namespace or SA name typo), or the role policy names a different ARN | `aws eks list-pod-identity-associations --cluster-name ... --namespace web`. The chart's `serviceAccount.name` must equal Terraform's `service_account` |
| `AccessDeniedException` from KMS (`kms:Decrypt`) | The secret is encrypted with a different key, or `kms:ViaService` names another region | `aws secretsmanager describe-secret --secret-id ... --query KmsKeyId` must equal `terraform output kms_key_arn` |
| Credentials error mentioning the node role, or `usePodIdentity` ignored | `usePodIdentity` isn't `"true"` (a string), or the Pod Identity agent isn't running on the node | Check the rendered SPC. `kubectl -n kube-system get ds eks-pod-identity-agent` |
| `ResourceNotFoundException: Secrets Manager can't find the specified secret` | Wrong name, or **wrong region**: ASCP defaults to the node's region | Set `aws.region` in the chart to where Terraform created the secrets |
| `FailedMount ... Invalid JMES Path: password` / `JMES Path ... not found` | **jmesPath key mismatch**: the JSON uses `Password` or `db_password`, or the value isn't JSON at all | `aws secretsmanager get-secret-value ... --query SecretString --output text \| python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)))'` prints the *keys only*. Match `path:` exactly; it is case-sensitive |
| Pod running but `/healthz` 503, `missing: [...]` | A file name the app expects isn't produced (`objectAlias` changed and `SECRETS_REQUIRED` not) | Both come from the same chart values; a manual edit of one of them is the usual cause. `kubectl exec ... -- ls /mnt/secrets` lists names only |
| Rotation not picked up | Driver rotation off, or the poll hasn't run yet | `enable_secret_rotation = true` in Terraform. Wait `rotationPollInterval + SECRETS_POLL_SECONDS`. `kubectl get secretproviderclasspodstatuses -o yaml` shows the object versions the driver has mounted |
| Synced Secret missing | `secretObjects` only syncs while a pod mounts the volume, and needs `sync_secret_enabled = true` | Enable both, or (preferred) read the files |

Never `cat` a secret file or run `get-secret-value` without `--query` during an incident
bridge or a screen share. List names, compare `/healthz` fingerprints, check keys.
