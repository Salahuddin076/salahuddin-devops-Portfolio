# No credentials here. In CI/local review this example has only ever been
# run through `terraform validate` -- never `plan`/`apply` -- so the
# provider's standard auth chain (az CLI login, a service principal via env
# vars, or workload identity federation in a pipeline) never actually needs
# to resolve to a real Azure AD token.
provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id

  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {
  tenant_id = var.tenant_id
}
