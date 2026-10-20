# No credentials here. The provider uses the standard chain (ADC, a service
# account key path in GOOGLE_APPLICATION_CREDENTIALS, or workload identity
# federation in CI) -- none of which this repo ever configures. This example
# has only ever been run through `terraform validate`, never `plan`/`apply`.
provider "google" {
  project = var.project_id
  region  = var.region
}
