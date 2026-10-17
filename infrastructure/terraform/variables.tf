variable "aws_region" {
  description = "AWS region for the complete pipeline."
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Resource name prefix."
  type        = string
  default     = "nz-migration-v2"
}

variable "environment" {
  description = "Deployment environment tag."
  type        = string
  default     = "demo"
}

variable "glue_worker_type" {
  description = "Smallest production Spark worker class suitable for this workload."
  type        = string
  default     = "G.1X"
}

variable "glue_number_of_workers" {
  description = "Glue Spark workers. Glue requires at least two G.1X workers."
  type        = number
  default     = 2

  validation {
    condition     = var.glue_number_of_workers >= 2 && var.glue_number_of_workers <= 5
    error_message = "glue_number_of_workers must stay between 2 and 5."
  }
}

variable "glue_timeout_minutes" {
  description = "Hard runtime ceiling for one uploaded release."
  type        = number
  default     = 15

  validation {
    condition     = var.glue_timeout_minutes >= 5 && var.glue_timeout_minutes <= 30
    error_message = "glue_timeout_minutes must stay between 5 and 30."
  }
}

variable "log_retention_days" {
  description = "CloudWatch retention for orchestration and Glue logs."
  type        = number
  default     = 14
}

variable "alert_email" {
  description = "Optional email endpoint for failure and cost notifications."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.alert_email == null ||
      can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    )
    error_message = "alert_email must be null or a valid email address."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly project-tagged AWS cost budget in US dollars."
  type        = number
  default     = 3

  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 3
    error_message = "monthly_budget_usd must be greater than zero and no more than three."
  }
}

variable "enable_lake_formation" {
  description = "Register the lake and apply catalog grants to consumer roles."
  type        = bool
  default     = true
}

variable "lake_formation_admin_principal_arn" {
  description = "IAM role or user ARN that administers Lake Formation. Defaults to the identity running Terraform for first-time bootstrap; set this to a dedicated deployment role for ongoing operations."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.lake_formation_admin_principal_arn == null ||
      can(regex("^arn:[^:]+:iam::[0-9]{12}:(role|user)/.+$", var.lake_formation_admin_principal_arn))
    )
    error_message = "lake_formation_admin_principal_arn must be null or an IAM role/user ARN."
  }
}
