variable "region" {
  description = "AWS region of the existing cluster."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names."
  type        = string
  default     = "prod"
}

variable "cluster_name" {
  description = "Existing EKS cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the cluster."
  type        = string
}

variable "data_subnet_ids" {
  description = "Private data subnets in at least two AZs."
  type        = list(string)
}

variable "node_security_group_id" {
  description = "Node security group, allowed to reach the data stores so the KEDA operator (no pod security group) can poll Redis."
  type        = string
}
