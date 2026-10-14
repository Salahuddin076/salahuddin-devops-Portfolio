# ---- identity ----------------------------------------------------------------

variable "name_prefix" {
  description = "Shared prefix, e.g. bluegreen. Resource names are <name_prefix>-<environment>-*."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase letters, digits or hyphens."
  }
}

variable "environment" {
  description = "Environment name: dev, staging or prod."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}

# ---- network, shared platform and load balancer ---------------------------------------------

variable "vpc_id" {
  description = "VPC for the ALB, tasks and hook Lambdas."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]{8,17}$", var.vpc_id))
    error_message = "vpc_id must look like vpc-0123456789abcdef0."
  }
}

variable "private_subnet_ids" {
  description = "Private subnets (with NAT or VPC endpoints) for tasks and hook Lambdas."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 2 && alltrue([for s in var.private_subnet_ids : can(regex("^subnet-[0-9a-f]{8,17}$", s))])
    error_message = "Provide at least two subnet IDs (subnet-...)."
  }
}

variable "cluster_name" {
  description = "Shared ECS cluster name (with FARGATE and FARGATE_SPOT capacity providers)."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets (two or more AZs) for this environment's internet-facing ALB."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) >= 2 && alltrue([for s in var.public_subnet_ids : can(regex("^subnet-[0-9a-f]{8,17}$", s))])
    error_message = "Provide at least two subnet IDs (subnet-...)."
  }
}

variable "production_ingress_cidrs" {
  description = "Who may reach the production listener (443) and the HTTP redirect (80)."
  type        = list(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = alltrue([for c in var.production_ingress_cidrs : can(cidrhost(c, 0))])
    error_message = "Every entry must be a valid CIDR."
  }
}

variable "enable_deletion_protection" {
  description = "ALB deletion protection. Keep true outside throwaway accounts."
  type        = bool
  default     = true
}

variable "certificate_arn" {
  description = "ACM certificate covering host_header, for the production and test listeners."
  type        = string
}

variable "ssl_policy" {
  description = "TLS policy for the HTTPS listeners."
  type        = string
  default     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}

variable "ecr_repository_arn" {
  description = "The only ECR repository the execution role may pull from."
  type        = string
}

# ---- routing -------------------------------------------------------------------

variable "host_header" {
  description = "Host name whose DNS aliases this environment's ALB, e.g. api.example.com. Used for the hook URLs."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9-]+\\.)+example\\.com$", var.host_header))
    error_message = "host_header must be a name under example.com (documentation-safe domain)."
  }
}

variable "test_listener_port" {
  description = "Test listener port on this environment's ALB."
  type        = number
  default     = 8443

  validation {
    condition     = var.test_listener_port >= 1024 && var.test_listener_port <= 65535 && var.test_listener_port != 443
    error_message = "test_listener_port must be 1024-65535."
  }
}

variable "test_listener_cidrs" {
  description = "Only these ranges may reach the test listener. Include the NAT gateway EIPs (/32) the hook Lambdas egress through."
  type        = list(string)

  validation {
    condition = length(var.test_listener_cidrs) > 0 && alltrue([
      for c in var.test_listener_cidrs : can(cidrhost(c, 0)) && !endswith(c, "/0")
    ])
    error_message = "test_listener_cidrs must be non-empty valid CIDRs, never 0.0.0.0/0."
  }
}

variable "health_check_path" {
  description = "Target group health check path."
  type        = string
  default     = "/healthz"
}

variable "deregistration_delay_seconds" {
  description = "Target group deregistration delay (connection draining) in seconds."
  type        = number
  default     = 30

  validation {
    condition     = var.deregistration_delay_seconds >= 0 && var.deregistration_delay_seconds <= 3600
    error_message = "deregistration_delay_seconds must be 0-3600."
  }
}

# ---- task ----------------------------------------------------------------------

variable "container_name" {
  description = "Container name; must match the appspec ContainerName."
  type        = string
  default     = "app"
}

variable "container_port" {
  description = "Container port; must match the appspec ContainerPort."
  type        = number
  default     = 8080
}

variable "bootstrap_image" {
  description = "Image for the first task definition revision only; CodeDeploy deployments register their own. Immutable tag or digest."
  type        = string

  validation {
    condition     = can(regex("^[^\\s]+(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})$", var.bootstrap_image)) && !endswith(lower(var.bootstrap_image), ":latest")
    error_message = "bootstrap_image needs an immutable tag or digest, never latest."
  }
}

variable "cpu" {
  description = "Task CPU units."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Task memory (MiB)."
  type        = number
  default     = 512
}

variable "cpu_architecture" {
  description = "Fargate runtime platform: ARM64 (Graviton) or X86_64. The image must be built for it."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "platform_version" {
  description = "Fargate platform version (1.4.0+ is needed for ARM64 on Fargate Spot)."
  type        = string
  default     = "LATEST"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the service and hook logs."
  type        = number
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch Logs retention value."
  }
}

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window for the app secret."
  type        = number
  default     = 30
}

# ---- capacity --------------------------------------------------------------------

variable "on_demand_base" {
  description = "Tasks always placed on FARGATE (on-demand) before weights apply."
  type        = number
  default     = 0

  validation {
    condition     = var.on_demand_base >= 0 && var.on_demand_base <= 100000
    error_message = "on_demand_base must be 0-100000."
  }
}

variable "on_demand_weight" {
  description = "Relative weight of FARGATE beyond the base."
  type        = number
  default     = 1

  validation {
    condition     = var.on_demand_weight >= 0 && var.on_demand_weight <= 1000
    error_message = "on_demand_weight must be 0-1000."
  }
}

variable "spot_weight" {
  description = "Relative weight of FARGATE_SPOT. Blue/green note: the replacement task set uses the same strategy, so both task sets may be on Spot."
  type        = number
  default     = 0

  validation {
    condition     = var.spot_weight >= 0 && var.spot_weight <= 1000
    error_message = "spot_weight must be 0-1000."
  }
}

# ---- scaling ---------------------------------------------------------------------

variable "desired_count" {
  description = "Initial desired count; autoscaling owns it afterwards."
  type        = number
  default     = 2
}

variable "min_capacity" {
  description = "Autoscaling minimum."
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Autoscaling maximum."
  type        = number
  default     = 4

  validation {
    condition     = var.max_capacity >= var.min_capacity && var.min_capacity >= 1
    error_message = "Need 1 <= min_capacity <= max_capacity."
  }
}

variable "cpu_target_percent" {
  description = "Target average CPU utilisation for target tracking."
  type        = number
  default     = 60
}

variable "requests_per_target" {
  description = "Target ALB requests per task per minute for target tracking."
  type        = number
  default     = 500
}

# ---- CodeDeploy ------------------------------------------------------------------

variable "deployment_config_name" {
  description = "Predefined CodeDeploy ECS deployment configuration."
  type        = string
  default     = "CodeDeployDefault.ECSCanary10Percent5Minutes"

  validation {
    condition = contains([
      "CodeDeployDefault.ECSAllAtOnce",
      "CodeDeployDefault.ECSLinear10PercentEvery1Minutes",
      "CodeDeployDefault.ECSLinear10PercentEvery3Minutes",
      "CodeDeployDefault.ECSCanary10Percent5Minutes",
      "CodeDeployDefault.ECSCanary10Percent15Minutes",
    ], var.deployment_config_name)
    error_message = "deployment_config_name must be a predefined CodeDeployDefault.ECS* configuration."
  }
}

variable "manual_reroute" {
  description = "true: wait for a manual reroute (aws deploy continue-deployment) before shifting traffic; false: shift as soon as green is ready."
  type        = bool
  default     = false
}

variable "reroute_wait_minutes" {
  description = "With manual_reroute, minutes to wait for the reroute before the deployment is stopped."
  type        = number
  default     = 60

  validation {
    condition     = var.reroute_wait_minutes >= 0 && var.reroute_wait_minutes <= 2880
    error_message = "reroute_wait_minutes must be 0-2880."
  }

  validation {
    condition     = !var.manual_reroute || var.reroute_wait_minutes >= 1
    error_message = "manual_reroute needs reroute_wait_minutes >= 1."
  }
}

variable "termination_wait_minutes" {
  description = "Minutes the original (blue) task set keeps running after the full shift; the rollback window."
  type        = number
  default     = 15

  validation {
    condition     = var.termination_wait_minutes >= 1 && var.termination_wait_minutes <= 2880
    error_message = "termination_wait_minutes must be 1-2880 (0 removes the rollback window)."
  }
}

variable "auto_rollback_events" {
  description = "Events that trigger automatic rollback."
  type        = list(string)
  default     = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]

  validation {
    condition     = contains(var.auto_rollback_events, "DEPLOYMENT_FAILURE") && alltrue([for e in var.auto_rollback_events : contains(["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM", "DEPLOYMENT_STOP_ON_REQUEST"], e)])
    error_message = "auto_rollback_events must include DEPLOYMENT_FAILURE and contain only valid events."
  }
}

variable "alarms_enabled" {
  description = "Create the 5xx and p95 latency alarms and wire them into the deployment group."
  type        = bool
  default     = true
}

variable "target_5xx_threshold" {
  description = "HTTPCode_Target_5XX_Count per minute that puts the alarm in ALARM."
  type        = number
  default     = 5
}

variable "p95_latency_threshold_seconds" {
  description = "p95 TargetResponseTime (seconds) that puts the alarm in ALARM."
  type        = number
  default     = 0.5
}

variable "alarm_evaluation_periods" {
  description = "One-minute periods over threshold before ALARM."
  type        = number
  default     = 2
}

# ---- lifecycle hooks -------------------------------------------------------------

variable "hooks_zip_path" {
  description = "Zip of src/hooks/*.py (see docs/operations.md, Packaging the hooks)."
  type        = string
}

variable "smoke_requests" {
  description = "Latency samples per hook run."
  type        = number
  default     = 20
}

variable "smoke_p95_budget_ms" {
  description = "p95 latency budget for the hook smoke tests."
  type        = number
  default     = 500
}

variable "smoke_request_timeout_seconds" {
  description = "Per-request timeout for the hook smoke tests."
  type        = number
  default     = 5
}
