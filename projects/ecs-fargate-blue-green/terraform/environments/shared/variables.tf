variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Owner tag."
  type        = string
  default     = "platform-team"
}

variable "name_prefix" {
  description = "Prefix shared by the platform and every environment."
  type        = string
  default     = "bluegreen"
}
