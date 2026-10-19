# Operations

## Rollout sequence, per service

1. **design** — service not yet assessed; no entry in
   `docs/compatibility-manifest.yaml`.
2. **native-agents** — CI builds and pushes a multi-arch manifest list for
   the service (`ci/Jenkinsfile`, or a GitHub Actions equivalent); both
   platforms recorded in the manifest with `build_method: native` wherever
   the service has native modules, base images pinned by digest per
   platform, and a scan recorded for both. `scripts/compatibility_check.py`
   must pass at this point.
3. **canary** — `helm upgrade <service> --set canary.enabled=true`. A small
   (typically 1-replica) Deployment comes up on the Graviton pool, sharing
   the existing Service with the stable (x86) Deployment. Watch error rate,
   p95/p99 latency and resource usage on the canary pods specifically
   (`kubectl top pods -l app.kubernetes.io/pool=canary`) against the stable
   pool's baseline. `compatibility_check.py` requires `image_scan.status:
   pass` on both platforms before this stage is allowed.
4. **partial** — widen the canary (`--set canary.replicaCount=N`) or flip
   `architecture=arm64` on a growing share of the fleet, keeping the x86
   pool at capacity the whole time. Nothing about the image changes; this
   is a sequence of `--set` calls against the same chart and the same tag.
5. **complete** — `architecture=arm64` for the whole stable Deployment,
   canary disabled, x86 node group scaled down (not deleted — see rollback
   window below).

## Before promoting past `native-agents`

```bash
python3 scripts/compatibility_check.py --fail-on warning
```

Run this against `docs/compatibility-manifest.yaml` (the default path) before
every stage change. CI runs it at `--fail-on warning` on every push that
touches the manifest or the docs (see `.github/workflows/graviton-arm64-migration.yml`).

## Rollback

**Scheduling rollback (seconds, no rebuild):**

```bash
# Turn off the canary pool
helm upgrade <release> helm/multiarch-app --reuse-values --set canary.enabled=false

# Or move the stable pool back to x86 entirely
helm upgrade <release> helm/multiarch-app --reuse-values --set architecture=amd64
```

Either command is a normal rolling update of the Deployment's `nodeSelector`.
The image tag doesn't change — it's the same manifest list, and the amd64
layer was built in the same `buildx` invocation as the arm64 layer that's
being rolled back from. There is nothing to rebuild and nothing to re-push.

**Capacity rollback (minutes, Terraform):** scale or remove the Graviton
node group in `terraform/examples/mixed-fleet` (`node_pools.graviton-migration`).
Keep this independent of the scheduling rollback above — removing Graviton
capacity before every pod has actually moved off it would leave the
remaining Graviton pods with nowhere to reschedule to.

**Rollback window:** keep the x86 node group at a non-zero `min_size` until
every service has been at `complete` for at least one full deploy cycle.
`aws_eks_node_group`'s `scaling_config.desired_size` is set to be ignored by
Terraform (`lifecycle.ignore_changes`) specifically so an on-call runbook or
Cluster Autoscaler can resize it during an incident without fighting the
next `terraform apply`.

## Incident: a service is slow or erroring only on the Graviton pool

1. Check whether the pod's actually running arm64:
   `kubectl get pod <pod> -o jsonpath='{.spec.nodeSelector}'` and
   `kubectl get node <node> -o jsonpath='{.metadata.labels.kubernetes\.io/arch}'`.
2. Pull the scheduling rollback above for that service immediately — it's
   cheaper than debugging under load.
3. Compare the two platforms' `image_scan` findings and `runtime_version` in
   `docs/compatibility-manifest.yaml`. A runtime version mismatch without a
   `runtime_version_note` is exactly the kind of drift
   `scripts/compatibility_check.py` (GC008) is meant to catch before this
   happens.
4. If the base images differ in anything beyond the pinned digest (check
   `docker buildx imagetools inspect <tag>` per platform), that's the next
   thing to compare — see [compatibility-checklist.md](compatibility-checklist.md#2-base-image-per-platform).

## Day to day

- `python3 -m unittest discover -s tests -v` before any change to the chart,
  the Terraform modules, or `scripts/compatibility_check.py`.
- `helm template ... | kubeconform -strict` whenever a template changes.
- Keep `docs/compatibility-manifest.yaml` as the single source of truth for
  rollout stage per service; don't let it drift from what's actually
  deployed (`kubectl get deploy -o jsonpath='{.spec.template.spec.nodeSelector}'`
  per release is the fast way to check).
