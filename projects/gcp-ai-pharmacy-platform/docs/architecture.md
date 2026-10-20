# Architecture

## Tiers

```mermaid
flowchart TB
    subgraph edge["Edge"]
        LB["Cloud Load Balancing\nHTTPS + Cloud Armor"]
    end
    subgraph gke["Private GKE cluster (regional)"]
        api["API pool (Java)"]
        ai["AI pool (inference)"]
    end
    subgraph data["Data"]
        sql["Cloud SQL (private IP, REGIONAL HA)"]
        sm["Secret Manager"]
    end
    subgraph ops["Delivery / ops"]
        cb["Cloud Build"]
        ar["Artifact Registry"]
        log["Cloud Logging"]
        mon["Cloud Monitoring"]
    end
    LB --> api
    api --> sql
    api --> sm
    ai --> sm
    cb --> ar --> gke
    gke --> log
    gke --> mon
```

## Request path

```mermaid
sequenceDiagram
    participant User
    participant LB as Cloud Load Balancing
    participant API as API pool pod
    participant WI as Workload Identity (metadata server)
    participant SM as Secret Manager
    participant SQL as Cloud SQL (private IP)

    User->>LB: HTTPS request
    LB->>API: forwarded (Cloud Armor evaluated at LB)
    API->>WI: request short-lived token for pharmacy-api GSA
    WI-->>API: access token (no key file involved)
    API->>SM: AccessSecretVersion(db-credentials)
    SM-->>API: credential JSON
    API->>SQL: query over private IP
    SQL-->>API: rows
    API-->>User: response
```

## Node-pool isolation

```mermaid
flowchart LR
    scheduler["kube-scheduler"]
    apipod["API pod\n(no toleration)"]
    aipod["AI pod\ntoleration: workload=ai-inference:NoSchedule"]
    apinode["API pool node\nlabel: workload-pool=api"]
    ainode["AI pool node\nlabel: workload-pool=ai-inference\ntaint: workload=ai-inference:NoSchedule"]

    scheduler -->|nodeSelector workload-pool=api| apipod --> apinode
    scheduler -->|nodeSelector + toleration match| aipod --> ainode
    apipod -.cannot schedule here, no toleration.-> ainode
```

The taint is what actually prevents an API pod from ever landing on an AI-pool node, even accidentally; the `nodeSelector` on both workloads is what stops the reverse (an AI pod landing on the API pool, where it isn't tainted away).

## Terraform module graph

```mermaid
flowchart LR
    apis["project-apis"] --> network
    apis --> gke["gke-cluster"]
    apis --> sql["cloud-sql"]
    apis --> delivery
    network --> gke
    network --> sql
    gke -->|workload_identity_bindings| secrets["secret-manager"]
    sql -->|database_password output| secrets
```

Each box is a separate module with its own `versions.tf`/`variables.tf`/`main.tf`/`outputs.tf`; in a real deployment each also gets its own state file (see `docs/decisions/0002-separate-state-per-layer.md`). `terraform/examples/reference` is the only place all of them are instantiated together.
