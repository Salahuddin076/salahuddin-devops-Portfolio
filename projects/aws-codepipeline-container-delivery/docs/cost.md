# Cost

> **Illustrative and approximate.** These are us-east-1 list prices as
> understood at the time of writing, rounded, before free tier and
> discounts. They are not quotes: check current AWS pricing before relying on
> any figure. Nothing in this repo has been deployed or billed.

## What drives the bill

Two different things cost money: **delivering** a release (pipeline and
build minutes) and **running** the services (Fargate around the clock).
At low release volume, running dominates by a wide margin.

| Driver | Pricing basis (approx.) | Lever |
|---|---|---|
| CodePipeline V2 | ~$0.002 per action execution minute, with a monthly free allowance (100 minutes at the time of writing). V2 has no per-pipeline monthly fee | Keep stages short. Check on the pricing page which action types count (approval waits have historically been excluded) |
| CodeBuild | Per build minute by compute type; Linux `general1.small` ~$0.005/min, `medium` ~$0.01/min | Small for tests, medium only if the image build is slow; Docker layer cache |
| ECR storage | ~$0.10/GB-month | Lifecycle policy: untagged after 7 days, keep the last 50 images |
| ECR data transfer | Free within the same region | Keep the pipeline, ECR and ECS in one region |
| Fargate (x86) | ~$0.0405/vCPU-hour + ~$0.0044/GB-hour | Right-size; arm64 is ~20% cheaper but needs an arm64 build |
| Secrets Manager | ~$0.40/secret-month + $0.05 per 10k API calls | 3 secrets; values are read only at task start or build start |
| KMS | ~$1/key-month + requests | One key; S3 Bucket Keys cut request charges |
| CloudWatch Logs | ~$0.50/GB ingested + storage | 30-day retention; one JSON line per request |
| Container Insights | Per metric and per GB of performance logs | Turn it off in sandboxes if the cost matters |
| NAT gateway | ~$0.045/hour + ~$0.045/GB processed | Not created by this module, but private subnets need it or VPC endpoints. Often the single largest line |

## Per release (approximate)

Assumptions: one commit through all stages, a small image (about 45 MB
compressed; the local build is ~210 MB uncompressed), and no Docker layer
cache.

| Step | Duration (assumed) | Pipeline action minutes | CodeBuild cost | Pipeline cost |
|---|---|---|---|---|
| Source | ~0.5 min | 0.5 | | $0.001 |
| Test (small) | ~2 min incl. provisioning | 2 | $0.010 | $0.004 |
| Build + scan + push (small) | ~5 min incl. Trivy DB download | 5 | $0.025 | $0.010 |
| DeployStaging | ~5 min until steady state | 5 | | $0.010 |
| ApproveProd | human time | (see note) | | |
| DeployProd | ~6 min | 6 | | $0.012 |
| **Total** | | **~18.5** | **~$0.035** | **~$0.037** |

So about **$0.07 per release**, or about $7 a month at 100 releases, before
the free allowances. Treat the proportions as the useful part, not the
cents. Deploy actions bill while they wait for ECS to reach steady state, so
a slow health check or a long deregistration delay costs pipeline minutes.

## Running cost per month (approximate)

| Item | Sizing | Approx. per month |
|---|---|---|
| Staging | 1 task x 0.25 vCPU / 0.5 GB, 730 h | ~$9 |
| Prod | 2 tasks x 0.25 vCPU / 0.5 GB, 730 h | ~$18 |
| ECR storage | 50 images, shared base layers, ~1 GB | ~$0.10 |
| Secrets Manager | 3 secrets | ~$1.20 |
| KMS | 1 key | ~$1 |
| Logs + Container Insights | low traffic | a few dollars |
| **Subtotal (this module)** | | **~$32** |
| NAT gateway (existing VPC, if used) | 1 AZ | ~$33 + data |

What changes the picture:

- **Staging doesn't need to run all night.** Scaling it to zero outside
  working hours (a scheduled action, or `desired_count = 0`) halves its
  line. The next deploy still works: the ECS action updates a zero-task
  service.
- **VPC endpoints vs NAT.** Interface endpoints for ECR (api and dkr),
  Secrets Manager and Logs cost about $7 per endpoint per AZ per month, plus
  the S3 gateway endpoint (free). Across two AZs that's in the same range as
  one NAT gateway, so compare on traffic and on the security posture
  (no internet egress at all).
- **Build image cache.** A local Docker layer cache on CodeBuild
  (`LOCAL_DOCKER_LAYER_CACHE`) shortens builds when consecutive builds land
  on the same host. Remote cache in ECR is more predictable.
- **Free tiers.** CodeBuild and CodePipeline free allowances can cover a
  low-volume pipeline entirely in many accounts.
