variable "name_prefix" {
  description = "Prefix for every resource name, e.g. bluegreen."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase letters, digits or hyphens."
  }
}

variable "ecr_repository_name" {
  description = "ECR repository for the application image."
  type        = string
  default     = "bluegreen-api"
}

variable "ecr_keep_images" {
  description = "How many images the ECR lifecycle policy keeps (old revisions are rollback targets)."
  type        = number
  default     = 50

  validation {
    condition     = var.ecr_keep_images >= 10
    error_message = "Keep at least 10 images so recent task definition revisions stay deployable."
  }
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
