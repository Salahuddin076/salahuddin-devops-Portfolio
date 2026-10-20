output "cluster_id" {
  description = "AKS cluster resource ID."
  value       = azurerm_kubernetes_cluster.this.id
}

output "cluster_name" {
  description = "AKS cluster name."
  value       = azurerm_kubernetes_cluster.this.name
}

output "oidc_issuer_url" {
  description = "Cluster's OIDC issuer URL -- the trust anchor every pod-level federated identity credential (azurerm_federated_identity_credential) is scoped to."
  value       = azurerm_kubernetes_cluster.this.oidc_issuer_url
}

output "kubelet_identity_object_id" {
  description = "Object ID of the kubelet identity AKS provisions for itself -- grant this AcrPull on the registry, never a shared imagePullSecret."
  value       = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

output "key_vault_secrets_provider_object_id" {
  description = "Object ID of the identity the Key Vault Secrets Provider (CSI driver) add-on runs as. Grant this Key Vault Secrets User on the vault so the driver itself can read secrets to mount -- separate from any individual pod's own workload identity."
  value       = azurerm_kubernetes_cluster.this.key_vault_secrets_provider[0].secret_identity[0].object_id
}

output "node_resource_group" {
  description = "The AKS-managed resource group holding node VMs, disks and the load balancer."
  value       = azurerm_kubernetes_cluster.this.node_resource_group
}
