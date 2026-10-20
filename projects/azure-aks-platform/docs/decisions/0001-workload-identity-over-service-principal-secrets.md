# 0001: Workload identity federation over service-principal secrets

## Status

Accepted.

## Context

Two distinct actors need an Entra identity in this platform: application pods (reading Key Vault secrets) and Azure DevOps pipelines (pushing images to ACR, and in a real deployment, running `terraform apply` or `kubectl` against the cluster). The traditional pattern for both is an Entra app registration/service principal with a client secret (or certificate) stored as a Kubernetes Secret or an Azure DevOps pipeline variable -- something that has to be generated, stored somewhere, rotated on a schedule, and can leak from a log, an environment dump, or a committed `.tfvars` file.

## Decision

Neither actor is ever issued a client secret in this repository.

- Pods authenticate via **Microsoft Entra Workload ID**: `azurerm_federated_identity_credential` (module `workload-identity`) trusts the AKS cluster's own OIDC issuer for an exact `system:serviceaccount:<namespace>:<name>` subject. A pod's projected Kubernetes service-account token is exchanged for a short-lived Entra token at request time; nothing is stored anywhere between requests.
- Azure DevOps pipelines authenticate via a **workload identity federation service connection**: `azuread_application_federated_identity_credential` (module `pipeline-identity`) trusts Azure DevOps's own OIDC issuer (`vstoken.dev.azure.com`) for the exact `sc://<org>/<project-id>/<service-connection-id>` subject the service connection presents.

## Consequences

- `tests/test_terraform_static.py` asserts, by grep, that `azuread_application_password` and `azuread_service_principal_password` never appear anywhere in this project -- a reviewer (or CI) catching a future PR that reaches for the old pattern doesn't have to read every file to notice.
- The bootstrapping order is less convenient than "generate a secret and paste it in": the Azure DevOps service connection's GUID has to exist *before* the federated credential that trusts it can be created (see `docs/operations.md`), which is a real operational step this reference documents rather than automates end-to-end (the ADO-side service connection creation is outside Terraform's reach without the Azure DevOps provider, which this project does not add).
- There is nothing to rotate. A compromised pipeline log or a `kubectl describe pod` can never leak a credential that was never written down in the first place.
