# Operations

> This stack has been validated with `terraform validate`, `helm lint` and
> `kubeconform`, and the failover logic has been exercised against fakes.
> It has never been deployed. Treat what follows as the procedure to
> rehearse in a sandbox account, not a record of production use. Check
> CLI flags against your tool versions before an incident, not during one.

## Two-phase bootstrap

The ALBs are created by the AWS Load Balancer Controller when the chart's
Ingress is applied. Terraform can't know their DNS names until then, so
Route 53 is created in a second pass.

**Phase 1: infrastructure and data**

```bash
cd terraform/environments/primary && cp terraform.tfvars.example terraform.tfvars
terraform init && terraform plan -out tfplan && terraform apply tfplan
cd ../dr && cp terraform.tfvars.example terraform.tfvars
terraform init && terraform plan -out tfplan && terraform apply tfplan

# Copy each region's `terraform output global_data_inputs` into
# environments/global/terraform.tfvars (primary = {...}, dr = {...}),
# with dns = { hosted_zone_id, record_name } and no ALBs yet.
cd ../global && terraform init && terraform plan -out tfplan && terraform apply tfplan
```

The global apply creates the Aurora Global Database (primary cluster,
then the secondary, which waits for the primary's instances), both
buckets with replication, the secret and its replica. It creates no
Route 53 resources yet, because `dns.primary_alb` and `dns.dr_alb` are
unset.

**Phase 2: controllers, chart, then DNS**

Per region (`aws eks update-kubeconfig --name dr-app-<region>-eks --region <region>`):

```bash
# 1. AWS Load Balancer Controller. The Pod Identity association for
#    kube-system/aws-load-balancer-controller already exists.
helm repo add eks https://aws.github.io/eks-charts
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system --set clusterName=dr-app-us-east-1-eks \
  --set serviceAccount.create=true --set serviceAccount.name=aws-load-balancer-controller \
  --set region=us-east-1 --set vpcId=<vpc id>

# 2. The app. Fill values-<region>.yaml from Terraform outputs first:
#    config.dbHost      <- environments/global: cluster_endpoints[region]
#    config.cacheHost   <- environments/<region>: cache_primary_endpoint
#    networkPolicy.*    <- environments/<region>: vpc_cidr, data_subnet_cidrs
kubectl create namespace orders
kubectl label namespace orders elbv2.k8s.aws/pod-readiness-gate-inject=enabled
helm upgrade --install dr-app helm/dr-app --namespace orders -f helm/dr-app/values-primary.yaml

# 3. Read the ALB name the controller created.
kubectl -n orders get ingress dr-app-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

Repeat for us-west-2 with `values-dr.yaml`. Then set `dns.primary_alb` and
`dns.dr_alb` (DNS name and the ALB's canonical hosted zone ID,
`aws elbv2 describe-load-balancers --names dr-app-us-east-1`) and apply
`environments/global` again. That creates the regional alias records, the
two deep health checks, the failover pair (us-east-1 PRIMARY) and the
health alarms.

The pod readiness gate label makes rollouts wait until the ALB target is
healthy, not only until the pod is Ready. Together with the preStop
sleep, it keeps a rolling update from dropping requests.

## Failover tooling setup

1. Build `config/failover.json` from `terraform output failover_config` in
   `environments/global`, plus the per-region `kube_context`, `chart` and
   `active_scale` (the API minimum and worker count the region should run
   at when it is the writer). `config/failover.example.json` shows the
   shape.
2. Put the state file and audit log somewhere both regions' operators can
   reach during an outage of either one. The reference writes local
   paths (`--state-file`, `--audit-log`). Real use: a bucket in a third
   region with versioning, and object lock on the audit log.
3. Rehearse with fakes first. The game day runbook runs the same commands
   against `--adapters fake`.

```bash
PYTHONPATH=src python3 -m failover --adapters aws --config config/failover.json status
```

The real adapters need AWS credentials that can describe and fail over the
global cluster, read CloudWatch, read and change the hosted zone, and
kube contexts for both clusters with rights to `helm upgrade` the release.

## Monitoring

| Signal | Where | Meaning |
|---|---|---|
| `AuroraGlobalDBReplicationLag` alarm | DR region, Terraform (`replication_lag_alarm_seconds`, default 5 s) | Planned failover is blocked; an unplanned one would lose more data |
| Route 53 `HealthCheckStatus` alarm per region | us-east-1 (Route 53 metrics live only there) | A region's deep health is failing; traffic may already be moving |
| S3 replication metrics (with RTC) | Both buckets | Objects pending or failing replication |
| `failover status` | CLI | One view: health, writer, lag, DNS role, workers, fenced, warnings |
| ALB `HTTPCode_Target_5XX_Count`, `TargetResponseTime` | Both ALBs | Standby health beyond the deep check |

Treat a failing DR health check as a P2 even when the primary is fine: a
standby that can't serve is not a standby.

## Routine changes

- **EKS upgrades: DR first.** Upgrade `environments/dr`, run the chart's
  smoke checks against `us-west-2.orders.example.com`, then upgrade the
  primary. Keep both regions on the same minor version, because the chart
  is validated against one Kubernetes version.
- **Aurora upgrades** go through the global cluster (`engine_version` in
  `environments/global`). Minor versions must match across regions, which
  is why `auto_minor_version_upgrade = false` on the instances.
- **Images:** configure ECR replication from us-east-1 to us-west-2. The
  DR values pull from the us-west-2 registry. A DR region that pulls
  images from the failed region can't scale up.
- **Chart releases** go to both regions in the same change. The DR
  release keeps `workers.enabled=false` while it is the standby. Releasing
  with the wrong values file to the wrong region is the most likely way to
  unfence a region by accident, so CI should pin values files to contexts.
- **Rotating the DB password:** bump `db_password_version` in
  `environments/global`. The new value is generated at apply time and
  written to the cluster and the secret together, never to state. Pods
  read the secret at start-up, so roll the deployments in both regions
  afterwards.
- **Changing the failover role:** never edit the Route 53 failover records
  by hand or in Terraform. After the first apply, Terraform ignores
  `failover_routing_policy`, and the CLI owns it.

## After a failover

- Update the DR region's `node_scaling` if the node group grew during the
  incident (Terraform ignores `desired_size`, but not `min` or `max`).
- After an **unplanned** failover the global root has drift: the DR
  cluster is no longer in the global cluster. Follow
  [runbooks/failback.md](../runbooks/failback.md) for the rebuild, which
  includes the Terraform state moves. Don't run a plain `terraform apply`
  in `environments/global` until then.
- Keep the old region's release at `workers.enabled=false` until failback
  completes. `failover status` warns if a fenced region runs workers.

## Tear-down (sandbox)

Deletion protection is on for the global cluster and both regional
clusters, and KMS keys have a 30-day deletion window. In this order: the
chart (so the controller deletes the ALBs), `environments/global` (after
turning off `deletion_protection`), then both regional roots. Buckets with
versioning must be emptied, including all versions, first.
