# Azure DevOps -> Entra ID federation: the pipeline's service connection
# authenticates as an Entra app registration via a federated credential
# issued by Azure DevOps's own OIDC issuer (vstoken.dev.azure.com). There is
# no client secret value anywhere in this module, in the service
# connection, or in pipeline YAML -- the whole point of a "workload identity
# federation" service connection type is that no secret is ever minted
# for it in the first place, so there's nothing to rotate and nothing to
# leak from a pipeline log.

resource "azuread_application" "ado_pipeline" {
  display_name = var.display_name
}

resource "azuread_service_principal" "ado_pipeline" {
  client_id = azuread_application.ado_pipeline.client_id
}

# Subject format for an Azure DevOps workload-identity-federation service
# connection: sc://{organization}/{project-id}/{service-connection-id}.
# The project ID and service connection ID are GUIDs assigned when the ADO
# project/service connection are created -- they don't exist until that
# manual (or separately-automated) ADO-side step runs, which is why they're
# plain input variables here rather than derived from anything in this
# module.
resource "azuread_application_federated_identity_credential" "ado_pipeline" {
  application_id = azuread_application.ado_pipeline.id
  display_name   = "azure-devops-federation"
  description    = "Azure DevOps workload identity federation service connection -- no client secret."
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://vstoken.dev.azure.com/${var.ado_organization}"
  subject        = "sc://${var.ado_organization}/${var.ado_project_id}/${var.ado_service_connection_id}"
}

# Least privilege: the pipeline identity can push images, nothing else. It
# is never granted Owner/Contributor on the subscription or resource group.
resource "azurerm_role_assignment" "ado_pipeline_acr_push" {
  scope                = var.acr_id
  role_definition_name = "AcrPush"
  principal_id         = azuread_service_principal.ado_pipeline.object_id
}
