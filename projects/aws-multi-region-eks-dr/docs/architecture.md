# Architecture

Warm standby across two regions. us-east-1 is the primary and us-west-2 is
the DR region; both are variables. Everything below is a reference
implementation: validated, never deployed.

## 1. High-level topology

```mermaid
flowchart TB
  U(["Clients"]) --> R53{{"Route 53<br/>orders.example.com<br/>failover: PRIMARY / SECONDARY"}}
  HC1["Health check<br/>us-east-1.orders.example.com<br/>/healthz/ready"] -.-> R53
  HC2["Health check<br/>us-west-2.orders.example.com<br/>/healthz/ready"] -.-> R53

  subgraph P["us-east-1 (primary)"]
    ALB1["ALB (created by the<br/>Load Balancer Controller)"] --> EKS1["EKS: API (HPA min 3)<br/>workers x2"]
    EKS1 --> AUR1[("Aurora writer<br/>2 instances")]
    EKS1 --> VK1[("Valkey")]
    EKS1 --> S31[("S3 bucket")]
  end

  subgraph D["us-west-2 (warm standby)"]
    ALB2["ALB"] --> EKS2["EKS: API (HPA min 2)<br/>workers 0"]
    EKS2 --> AUR2[("Aurora secondary<br/>1 instance, read-only")]
    EKS2 --> VK2[("Valkey (cold-start OK)")]
    EKS2 --> S32[("S3 bucket")]
  end

  R53 -->|PRIMARY| ALB1
  R53 -.->|SECONDARY| ALB2
  AUR1 ==>|"Global Database<br/>storage replication"| AUR2
  S31 ==>|"CRR (two-way)"| S32
  SM1["Secrets Manager<br/>dr-app/aurora-master"] ==>|replica| SM2["Secrets Manager<br/>replica"]
```

The standby is not idle. Its API pods serve `/healthz/ready` against the
Aurora secondary and the local Valkey, so Route 53 probes the full DR
path continuously. Workers are the only component kept at zero: they
write, and only the writer region may write ([ADR 0005](decisions/0005-fencing-before-promotion.md)).

## 2. One region in detail

Both regions use the same `regional-stack` module.

```mermaid
flowchart LR
  subgraph VPC["VPC 10.10.0.0/16 (DR: 10.20.0.0/16), 3 AZs"]
    subgraph PUB["public /20 x3"]
      ALB["ALB<br/>(Ingress, target-type ip)"]
      NAT["NAT gateway<br/>per AZ (DR: single)"]
    end
    subgraph PRIV["private /19 x3"]
      NG["Managed node group<br/>AL2023 Graviton<br/>min/desired/max per region"]
      subgraph NS["namespace orders"]
        API["order-api pods<br/>HPA + PDB + topology spread"]
        WK["order-worker pods<br/>replicas = workers.enabled ? n : 0"]
      end
      LBC["aws-load-balancer-controller<br/>(kube-system)"]
      PIA["eks-pod-identity-agent"]
    end
    subgraph DATA["data /22 x3 (no internet route)"]
      AUR[("Aurora PostgreSQL<br/>SG: 5432 from cluster SG")]
      VK[("Valkey, TLS required<br/>SG: 6379 from cluster SG")]
    end
    S3E["S3 gateway endpoint"]
  end
  ALB -->|"pod IPs :8080<br/>(NetworkPolicy: from VPC CIDR)"| API
  API --> AUR
  API --> VK
  WK --> AUR
  LBC -.->|"creates/updates"| ALB
  PIA -.->|"credentials"| API
  PIA -.->|"credentials"| LBC
  KMS["Regional CMK<br/>EKS secrets, Aurora, S3,<br/>Valkey, Secrets Manager, logs"] -.-> AUR
  KMS -.-> VK
```

Notes:

- **The ALB is not in Terraform.** The AWS Load Balancer Controller creates
  it from the chart's Ingress (`ingressClassName: alb`, `target-type: ip`,
  health check on `/healthz/ready`). Terraform creates the controller's IAM
  role and its Pod Identity association, and tags the public subnets
  `kubernetes.io/role/elb=1` so the controller can find them. The ALB DNS
  name is read after the chart is installed and fed to Route 53
  ([operations.md](operations.md#two-phase-bootstrap)).
- **Access entries, not aws-auth.** The cluster runs with
  `authentication_mode = "API"` and
  `bootstrap_cluster_creator_admin_permissions = false`. Admin roles come
  from `cluster_admin_principal_arns`.
- **Pod Identity, not IRSA.** There is no OIDC provider. Two roles trust
  `pods.eks.amazonaws.com`, with conditions on `aws:SourceAccount` and the
  cluster ARN: one for the order API (its secret, its bucket, its key,
  region-scoped) and one for the Load Balancer Controller.
- **Readiness is deep, liveness is shallow.** `/healthz/ready` checks the
  DB connection, the cache and the loaded secret, but not that the
  database is writable, so the standby is "ready". `/healthz/live` checks
  only the process, so a database outage doesn't restart every pod.
- **NetworkPolicy is enforced** by the VPC CNI (`enableNetworkPolicy` on
  the add-on): default deny, ingress only from the VPC CIDR on 8080, and
  egress only to DNS, the data subnets on 5432 and 6379, the Pod Identity
  agent, and HTTPS.

## 3. Data replication

```mermaid
flowchart LR
  subgraph P["us-east-1"]
    W[("Aurora cluster<br/>dr-app-us-east-1<br/>writer, CMK A")]
    B1[("example-dr-app-data-us-east-1<br/>versioned, SSE-KMS A")]
    S1["Secret dr-app/aurora-master<br/>CMK A"]
  end
  subgraph D["us-west-2"]
    R[("Aurora cluster<br/>dr-app-us-west-2<br/>secondary, CMK B")]
    B2[("example-dr-app-data-us-west-2<br/>versioned, SSE-KMS B")]
    S2["Replica secret<br/>same name, CMK B"]
    VK2[("Valkey: not replicated")]
  end
  W ==>|"Global Database: async storage replication<br/>lag metric AuroraGlobalDBReplicationLag"| R
  B1 ==>|"CRR, re-encrypted with CMK B<br/>RTC optional (15 min SLA)"| B2
  B2 -.->|"CRR back (replica modification sync)"| B1
  S1 ==>|"Secrets Manager replication"| S2
```

| Data | Mechanism | Planned failover | Unplanned failover |
|---|---|---|---|
| Orders (Aurora) | Global Database storage replication | No loss (switchover waits for catch-up) | Loses the un-replicated tail (the lag at failure) |
| Objects (S3) | CRR, optional RTC | Writes in flight may arrive a few minutes late | Objects not yet replicated are missing until the source is back |
| DB credentials | Secrets Manager replica | Same secret name, read locally | Replica can be promoted (`stop-replication-to-replica`) to rotate while the primary is down |
| Cache (Valkey) | None | Cold start | Cold start ([ADR 0003](decisions/0003-valkey-rebuildable.md)) |
| Job claims (`processed_jobs`) | In Aurora, so replicated with the data | No duplicates | Claims in the lost tail are re-run; downstream idempotency keys absorb it |

Each region has its own key, and nothing uses multi-Region KMS keys: a
key disabled or scheduled for deletion in one region does not take the
other region's data with it.

## 4. Failover sequence (planned)

```mermaid
sequenceDiagram
  autonumber
  actor IC as Incident commander
  participant CLI as failover CLI
  participant ST as State file + audit log
  participant K1 as EKS us-east-1
  participant RDS as Aurora Global DB
  participant K2 as EKS us-west-2
  participant R53 as Route 53

  IC->>CLI: plan --mode planned
  CLI-->>IC: ordered steps (nothing executed)
  IC->>CLI: execute --mode planned --target us-west-2 --confirm dr-app-global
  CLI->>ST: run_started
  CLI->>RDS: pre-checks: writer = us-east-1, lag < 5 s
  CLI->>K2: health /healthz/ready
  CLI->>K1: helm upgrade workers.enabled=false (fence)
  CLI->>ST: us-east-1 fenced
  CLI->>RDS: failover-global-cluster --switchover (target us-west-2)
  RDS-->>CLI: us-west-2 is writer (no data loss)
  CLI->>ST: writer us-west-2, epoch+1
  CLI->>K2: helm upgrade api.autoscaling.minReplicas=3, workers.enabled=true
  CLI->>R53: UPSERT us-west-2 PRIMARY, us-east-1 SECONDARY (one batch)
  CLI->>K2: post-checks: healthy, writer, workers > 0
  CLI->>K1: post-check: workers = 0
  CLI->>ST: run_completed
```

The unplanned sequence has the same shape, with three differences: the
pre-check requires the primary to be unhealthy; the fence is skipped (and
recorded as skipped) when us-east-1's EKS API doesn't answer; and the
promote step is `remove-from-global-cluster` followed by a wait for a
standalone writer ([ADR 0002](decisions/0002-managed-switchover-vs-detach-promote.md)).
Every step is saved before the next one starts, so a crash at any point
resumes at the first step that isn't done.

## Where Route 53 fits in an outage

Route 53 health checks fail over traffic on their own when the primary's
`/healthz/ready` fails `failure_threshold` times. The CLI's flip-dns step
does not replace that. It makes the result stick: the DR record becomes
PRIMARY, so traffic does not go back to the fenced region when its health
check recovers. Route 53's control plane (record changes) lives in
us-east-1. If us-east-1 is impaired, the change call can fail while the
data plane (health-check failover) keeps working. The step then fails,
the run stays resumable, and traffic is already on DR because of the
health check. [runbooks/unplanned-failover.md](../runbooks/unplanned-failover.md)
covers this case.
