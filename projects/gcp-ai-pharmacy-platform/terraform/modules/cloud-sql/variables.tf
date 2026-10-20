variable "project_id" {
  description = "GCP project ID the instance is created in. Synthetic in this reference."
  type        = string
}

variable "region" {
  description = "Region for the Cloud SQL instance. Should match the GKE cluster's region to keep the Java services' queries in-region."
  type        = string
}

variable "instance_name" {
  description = "Name of the Cloud SQL instance."
  type        = string
  default     = "pharmacy-db"
}

variable "database_version" {
  description = "Cloud SQL database engine/version."
  type        = string
  default     = "POSTGRES_15"
}

variable "tier" {
  description = "Machine tier for the instance, e.g. db-custom-4-16384."
  type        = string
  default     = "db-custom-2-8192"
}

variable "availability_type" {
  description = "REGIONAL gives a synchronous standby in a second zone with automatic failover (Cloud SQL HA); ZONAL has none. Private, auditable healthcare-adjacent data defaults to REGIONAL."
  type        = string
  default     = "REGIONAL"

  validation {
    condition     = contains(["REGIONAL", "ZONAL"], var.availability_type)
    error_message = "availability_type must be REGIONAL or ZONAL."
  }
}

variable "network_id" {
  description = "Self-link / ID of the VPC to attach the private IP to (module.network.network_id)."
  type        = string
}

variable "private_vpc_connection" {
  description = "The servicenetworking peering connection this instance's private IP depends on (module.network.private_vpc_connection). Passed through purely to create an explicit depends_on."
  type        = any
}

variable "database_name" {
  description = "Name of the application database created inside the instance."
  type        = string
  default     = "pharmacy"
}

variable "database_user" {
  description = "Name of the application database user created inside the instance."
  type        = string
  default     = "pharmacy_app"
}

variable "deletion_protection" {
  description = "Cloud SQL deletion_protection flag. False here only because this reference is never deployed; production should set this true."
  type        = bool
  default     = false
}

variable "backup_start_time" {
  description = "UTC HH:MM window daily backups start in."
  type        = string
  default     = "03:00"
}

variable "transaction_log_retention_days" {
  description = "How many days of transaction logs to retain for point-in-time recovery."
  type        = number
  default     = 7
}
