variable "name_prefix" {
  description = "Prefix for every resource name, e.g. delivery-demo. Lowercase letters, digits and hyphens."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name_prefix))
    error_message = "name_prefix must be 3-24 characters: a lowercase letter followed by lowercase letters, digits or hyphens."
  }
}

# ----------------------------------------------------------------------------- source

variable "repository_full_id" {
  description = "GitHub repository as owner/name, read through the CodeConnections connection."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$", var.repository_full_id))
    error_message = "repository_full_id must look like owner/repository."
  }
}

variable "branch" {
  description = "Branch that triggers the pipeline."
  type        = string
  default     = "main"

  validation {
    condition     = length(var.branch) > 0 && !can(regex("[\\s~^:?*\\[\\\\]", var.branch))
    error_message = "branch must be a valid git branch name."
  }
}

variable "project_dir" {
  description = "Path of this project inside the repository (the buildspecs cd into it). Use \".\" for a standalone repository."
  type        = string
  default     = "projects/aws-codepipeline-container-delivery"

  validation {
    condition     = var.project_dir == "." || can(regex("^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$", var.project_dir))
    error_message = "project_dir must be \".\" or a relative path without leading or trailing slashes."
  }
}

variable "trigger_file_paths" {
  description = "Only pushes touching these paths start the pipeline (CodePipeline V2 trigger filter). Empty means every push to the branch."
  type        = list(string)
  default     = []
}

# ----------------------------------------------------------------------------- networking

variable "vpc_id" {
  description = "Existing VPC for the ECS services (and CodeBuild when codebuild_in_vpc is true). This module does not build a VPC."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]{8}([0-9a-f]{9})?$", var.vpc_id))
    error_message = "vpc_id must look like vpc-0123456789abcdef0."
  }
}

variable "subnet_ids" {
  description = "Private subnets (at least two, in different AZs) for the Fargate tasks. They need a route to ECR, Secrets Manager and CloudWatch Logs: a NAT gateway or VPC endpoints."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2 && alltrue([for s in var.subnet_ids : can(regex("^subnet-[0-9a-f]{8}([0-9a-f]{9})?$", s))])
    error_message = "subnet_ids must hold at least two IDs like subnet-0123456789abcdef0."
  }

  validation {
    condition     = length(distinct(var.subnet_ids)) == length(var.subnet_ids)
    error_message = "subnet_ids must not contain duplicates."
  }
}

variable "assign_public_ip" {
  description = "Give tasks a public IP. Keep false with private subnets; true only for a sandbox VPC without NAT."
  type        = bool
  default     = false
}

variable "ingress_cidr_blocks" {
  description = "CIDRs allowed to reach the container port (for example a load balancer subnet). Empty means no inbound access."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.ingress_cidr_blocks : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "ingress_cidr_blocks must be valid CIDRs and must not include 0.0.0.0/0."
  }
}

variable "codebuild_in_vpc" {
  description = "Run the CodeBuild projects inside the VPC (subnet_ids). The subnets then need NAT or endpoints for GitHub, ECR, S3 and the Trivy download."
  type        = bool
  default     = false
}

# ----------------------------------------------------------------------------- build

variable "codebuild_image" {
  description = "CodeBuild managed image."
  type        = string
  default     = "aws/codebuild/standard:7.0"
}

variable "codebuild_compute_type" {
  description = "CodeBuild compute type."
  type        = string
  default     = "BUILD_GENERAL1_SMALL"

  validation {
    condition     = contains(["BUILD_GENERAL1_SMALL", "BUILD_GENERAL1_MEDIUM", "BUILD_GENERAL1_LARGE"], var.codebuild_compute_type)
    error_message = "codebuild_compute_type must be BUILD_GENERAL1_SMALL, _MEDIUM or _LARGE."
  }
}

variable "build_timeout_minutes" {
  description = "Timeout for each CodeBuild build."
  type        = number
  default     = 20

  validation {
    condition     = var.build_timeout_minutes >= 5 && var.build_timeout_minutes <= 120
    error_message = "build_timeout_minutes must be between 5 and 120."
  }
}

variable "registry_secret_name" {
  description = "Name of the Docker Hub credentials secret. Must match env.secrets-manager in buildspec-build.yml."
  type        = string
  default     = "container-delivery/ci/dockerhub"

  validation {
    condition     = can(regex("^[A-Za-z0-9/_+=.@-]{1,512}$", var.registry_secret_name))
    error_message = "registry_secret_name contains characters Secrets Manager does not allow."
  }
}

variable "ecr_keep_images" {
  description = "How many images the ECR lifecycle policy keeps. Older SHAs can no longer be redeployed without a rebuild."
  type        = number
  default     = 50

  validation {
    condition     = var.ecr_keep_images >= 10 && var.ecr_keep_images <= 1000
    error_message = "ecr_keep_images must be between 10 and 1000."
  }
}

# ----------------------------------------------------------------------------- run

variable "container_name" {
  description = "Container name in both task definitions; written into imagedefinitions.json by the build."
  type        = string
  default     = "app"

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,255}$", var.container_name))
    error_message = "container_name may contain only letters, digits, hyphens and underscores."
  }
}

variable "container_port" {
  description = "Port the app listens on."
  type        = number
  default     = 8080

  validation {
    condition     = var.container_port >= 1024 && var.container_port <= 65535
    error_message = "container_port must be an unprivileged port (1024-65535); the container runs as non-root."
  }
}

variable "environments" {
  description = "Per-environment task size and desired count. Exactly staging and prod. Set desired_count to 0 for the first apply (see docs/operations.md)."
  type = map(object({
    cpu           = number
    memory        = number
    desired_count = number
  }))
  default = {
    staging = { cpu = 256, memory = 512, desired_count = 1 }
    prod    = { cpu = 256, memory = 512, desired_count = 2 }
  }

  validation {
    condition     = toset(keys(var.environments)) == toset(["staging", "prod"])
    error_message = "environments must define exactly staging and prod."
  }

  validation {
    condition     = alltrue([for e in values(var.environments) : contains([256, 512, 1024, 2048, 4096], e.cpu)])
    error_message = "cpu must be a Fargate value: 256, 512, 1024, 2048 or 4096."
  }

  validation {
    condition     = alltrue([for e in values(var.environments) : e.memory >= 512 && e.memory <= 30720 && e.desired_count >= 0 && e.desired_count <= 20])
    error_message = "memory must be 512-30720 MiB and desired_count 0-20."
  }
}

variable "log_retention_days" {
  description = "Retention for the ECS and CodeBuild log groups."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a value CloudWatch Logs accepts (1, 3, 5, 7, 14, 30, 60, 90, ...)."
  }
}

# ----------------------------------------------------------------------------- approval and lifecycle

variable "approval_emails" {
  description = "Email addresses subscribed to the prod approval topic. Each must confirm the subscription."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.approval_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "approval_emails must be email addresses."
  }
}

variable "approval_timeout_minutes" {
  description = "How long the manual approval waits before the execution fails (CodePipeline maximum is 7 days)."
  type        = number
  default     = 1440

  validation {
    condition     = var.approval_timeout_minutes >= 5 && var.approval_timeout_minutes <= 10080
    error_message = "approval_timeout_minutes must be between 5 and 10080."
  }
}

variable "artifact_retention_days" {
  description = "Days before pipeline artifacts expire from the artifact bucket."
  type        = number
  default     = 30

  validation {
    condition     = var.artifact_retention_days >= 1
    error_message = "artifact_retention_days must be at least 1."
  }
}

variable "force_destroy" {
  description = "Allow destroy to delete a non-empty artifact bucket and ECR repository. Keep false outside sandboxes."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags for every resource (on top of provider default_tags)."
  type        = map(string)
  default     = {}
}
