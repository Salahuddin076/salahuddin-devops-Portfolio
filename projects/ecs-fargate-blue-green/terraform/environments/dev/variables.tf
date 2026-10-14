variable "region" {
  description = "AWS region (same as the shared root)."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Owner tag."
  type        = string
  default     = "platform-team"
}

variable "name_prefix" {
  description = "Prefix used by the shared root."
  type        = string
  default     = "bluegreen"
}

variable "vpc_id" {
  description = "Existing VPC."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for this environment's ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for tasks and hook Lambdas."
  type        = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate covering this environment's host name."
  type        = string
}

variable "bootstrap_image" {
  description = "Immutable image for the first task definition revision."
  type        = string
}

variable "hooks_zip_path" {
  description = "Zip of src/hooks/*.py."
  type        = string
  default     = "../../../build/hooks.zip"
}

variable "ecr_repository_name" {
  description = "ECR repository created by the shared root."
  type        = string
  default     = "bluegreen-api"
}
