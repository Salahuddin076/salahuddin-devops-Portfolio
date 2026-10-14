# ADR 0002: EKS Pod Identity over IRSA for ASCP

- **Status:** Accepted
- **Date:** 2026-10-14
- **Context:** eks-secrets-store-csi (portfolio implementation)

## Context

ASCP calls Secrets Manager with the IAM identity of the pod that mounts the volume. EKS
offers two ways to give a ServiceAccount an IAM role, and ASCP supports both
(`usePodIdentity: "true"` in the SecretProviderClass, or IRSA by default).

## Decision

Use **EKS Pod Identity** (`aws_eks_pod_identity_association`). IRSA is documented below as
the alternative. It is not in the code: carrying both would double the IAM surface and the
test matrix for no benefit.

## Comparison

| | Pod Identity | IRSA |
|---|---|---|
| Cluster prerequisite | `eks-pod-identity-agent` add-on | An IAM OIDC provider per cluster (`aws_iam_openid_connect_provider`) |
| Trust policy | `Service: pods.eks.amazonaws.com`, same for every cluster. Scoped with `aws:SourceArn` = cluster ARN | `Federated: <cluster OIDC provider>`, with `sub` = `system:serviceaccount:<ns>:<sa>` and `aud` conditions. Different per cluster |
| Binding | An EKS API object (association). Nothing on the ServiceAccount | The annotation `eks.amazonaws.com/role-arn` on the ServiceAccount (in the chart) |
| Moving to a new cluster (blue/green, DR) | Create associations; the role is unchanged | Add the new OIDC provider to every role's trust policy |
| Session tags | `eks-cluster-name`, `kubernetes-namespace`, `kubernetes-service-account` and more, usable in ABAC conditions | None from EKS |
| Works on | EKS (EC2 nodes). Not Fargate at the time of writing | EKS including Fargate, self-managed clusters with OIDC |
| Role trust-policy size limit | Not a concern (one statement) | A concern with many clusters per role |

## Why Pod Identity here

- The chart stays identity-agnostic: no role ARN in Helm values. Platform Terraform owns
  the binding, next to the role it binds, in one plan.
- The trust policy doesn't change per cluster, which matters for the multi-region sibling
  (two clusters, one role design).
- ASCP supports it directly with one parameter.

## The IRSA alternative (not implemented)

If the cluster couldn't run the agent, or the organization standardizes on IRSA (Fargate
isn't a reason here: the CSI driver is a DaemonSet and doesn't run on Fargate either):

```hcl
# Trust policy instead of pods.eks.amazonaws.com:
principals {
  type        = "Federated"
  identifiers = [aws_iam_openid_connect_provider.this.arn]
}
actions = ["sts:AssumeRoleWithWebIdentity"]
condition {
  test     = "StringEquals"
  variable = "${local.oidc_host}:sub"
  values   = ["system:serviceaccount:web:secure-frontend"]
}
condition {
  test     = "StringEquals"
  variable = "${local.oidc_host}:aud"
  values   = ["sts.amazonaws.com"]
}
```

The chart would set `aws.usePodIdentity: false` and annotate the ServiceAccount with
`eks.amazonaws.com/role-arn`. The policy (two secrets, ViaService decrypt) is identical.
`automountServiceAccountToken: false` still holds: the IRSA webhook injects its own
projected token, and the CSI driver gets one from kubelet.

## Consequences

- The Pod Identity agent must run on every node that runs consumers. The module can manage
  it (`manage_pod_identity_agent_addon`), or leave it to the cluster stack.
- Pod Identity injects credentials into *every* container in the pod, the app included,
  even though only ASCP needs them. The app's NetworkPolicy has no route to the agent
  ([security.md](../security.md#network)).
