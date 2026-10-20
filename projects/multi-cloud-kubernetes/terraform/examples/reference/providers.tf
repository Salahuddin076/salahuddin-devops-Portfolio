# No credentials here. Each provider uses its standard auth chain (AWS SDK
# chain, az CLI/workload identity federation, ADC) -- none of which this
# repo ever configures. This example has only ever been run through
# `terraform validate`, never `plan`/`apply`: it exists so the three identity
# bindings in terraform/modules/identity-bindings can be exercised together
# against three real providers' schemas, side by side, without three real
# cluster stacks.

provider "aws" {
  region = "us-east-1"
}

provider "azurerm" {
  subscription_id = var.azure_subscription_id
  tenant_id       = var.azure_tenant_id

  features {}
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-central1"
}
