# Cost (illustrative)

All figures are illustrative assumptions for discussion, not quotes and not
production numbers. Check current pricing for your region.

## What the GitOps layer adds

| Item | Assumption | Rough monthly figure |
|---|---|---|
| Argo CD (controller, repo server x2, server, ApplicationSet x2, Redis, notifications) | about 1.5 vCPU and 3 GiB requested on existing nodes | the share of one small node, on the order of USD 30-60 |
| Argo Rollouts controller | 0.1 vCPU, 128 MiB | negligible |
| External Secrets controller | 0.1 vCPU, 128 MiB | negligible |
| AWS Secrets Manager | 3 secrets, refresh every hour from 1-2 pods each | about USD 1.20 for storage plus a few cents for API calls |
| Canary surge in prod | `maxSurge: 25%` during a rollout, minutes per deploy | negligible unless deploys are very frequent |
| CI minutes | test, build and bump per merge, a few minutes on hosted runners | within the free tier for a small team |

## Levers

- **One Argo CD for all environments** (as here) is the cheapest. A separate
  Argo CD per cluster isolates failures and credentials better at the cost
  of running the stack more than once.
- **Dev scales to one replica** (`autoscaling.minReplicas: 1`,
  `pdb.minAvailable: 0`) and could be scaled to zero out of hours with a
  KEDA cron trigger.
- **Secret refresh interval**: `1h` keeps API calls low; shorten it only for
  secrets that rotate often.
- **Canary without a service mesh**: replica-ratio weights need no extra
  proxies or load balancers. A traffic router (NGINX, ALB or Gateway API)
  gives exact weights; with NGINX it costs nothing extra, a mesh adds
  sidecars.
