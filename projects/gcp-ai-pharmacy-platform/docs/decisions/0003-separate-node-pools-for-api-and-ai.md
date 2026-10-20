# 0003: Separate node pools for the API and AI workloads

## Status

Accepted.

## Context

The Java API and the AI inference workers have opposite scaling shapes: the API is steady, latency-sensitive, and wants to stay warm; inference is bursty, batch-shaped, and often idle entirely outside working hours. Running both on one node pool means sizing that pool for peak combined demand, so an inference burst can starve the API of CPU/memory it was relying on, or the pool has to be kept oversized "just in case" to protect the API.

## Decision

Two node pools, defined from the same `var.node_pools` map in `modules/gke-cluster` but given very different shapes in the reference wiring:

- **`api`**: `e2-standard-4`, on-demand, `min_count = 2`, no taint.
- **`ai`**: `n2-highmem-8`, spot, `min_count = 0` (scales to zero), tainted `workload=ai-inference:NoSchedule`.

The AI pool's taint, combined with a matching `nodeSelector` + `toleration` pair on the AI workload's Helm release, is what actually enforces the isolation — not resource requests/limits, which only express a preference the scheduler can still override under pressure.

## Consequences

- An inference burst can grow the AI pool up to its own `max_count` ceiling without ever touching the API pool's node count or its autoscaler budget.
- The AI pool scaling to zero outside working hours (or whenever there's no pending inference work) is the main cost lever documented in `docs/cost.md` — an always-on AI pool at the same machine type would cost several times as much.
- This requires discipline on both sides of the scheduling contract: a new workload meant for the AI pool that forgets its `toleration` will simply fail to schedule there (visible immediately as a Pending pod), while a workload that forgets its `nodeSelector` could land on *either* pool depending on what's untainted — which is why both values are asserted independently in `tests/test_helm_static.py` rather than relying on a human to remember to set both.
- Spot pricing on the AI pool means inference workers must tolerate preemption; this is acceptable for a retryable, stateless inference request but would not be for a stateful workload.
