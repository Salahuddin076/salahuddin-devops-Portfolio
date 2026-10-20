variable "service_account_name" {
  description = "Kubernetes ServiceAccount name, identical in every cluster. This is what lets one Helm chart's serviceaccount.yaml work unmodified on EKS, AKS and GKE -- all three identity bindings below trust this exact name/namespace pair, and only the cloud-side identity (IAM role / managed identity / service account) differs."
  type        = string
  default     = "portable-service"
}

variable "service_account_namespace" {
  description = "Kubernetes namespace the ServiceAccount lives in, identical in every cluster."
  type        = string
  default     = "portable-service"
}

variable "aws_oidc_provider_arn" {
  description = "EKS cluster's IAM OIDC provider ARN (aws_iam_openid_connect_provider.this.arn in a real cluster root). Synthetic placeholder in this reference -- this module is never applied."
  type        = string
  default     = "arn:aws:iam::111111111111:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/EXAMPLEEXAMPLEEXAMPLE"
}

variable "aws_oidc_provider_url" {
  description = "Same OIDC provider's issuer host and path, without the https:// scheme -- used verbatim as the condition-key prefix in the IRSA trust policy (<issuer>:sub, <issuer>:aud)."
  type        = string
  default     = "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLEEXAMPLEEXAMPLE"
}

variable "azure_resource_group_name" {
  description = "Resource group for the user-assigned managed identity backing Entra Workload ID."
  type        = string
  default     = "example-multi-cloud-rg"
}

variable "azure_location" {
  description = "Azure region for the managed identity."
  type        = string
  default     = "eastus"
}

variable "azure_oidc_issuer_url" {
  description = "AKS cluster's OIDC issuer URL (module.aks.oidc_issuer_url in a real cluster root) -- the federated credential's trust anchor."
  type        = string
  default     = "https://eastus.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/11111111-1111-1111-1111-111111111111/"
}

variable "gcp_project_id" {
  description = "GCP project ID. Synthetic placeholder in this reference -- never a real project."
  type        = string
  default     = "example-multi-cloud"
}

variable "tags" {
  description = "Tags/labels applied where the provider supports them (AWS and Azure)."
  type        = map(string)
  default = {
    project    = "multi-cloud-kubernetes"
    managed-by = "terraform"
  }
}
