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

variable "deploy_compute" {
  description = "Create Lambda and Step Functions after a container image is pushed."
  type        = bool
  default     = false
}

variable "container_image_uri" {
  description = "Immutable ECR image URI including its sha256 digest."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      !var.deploy_compute ||
      (var.container_image_uri != null && can(regex("@sha256:[0-9a-f]{64}$", var.container_image_uri)))
    )
    error_message = "When deploy_compute is true, container_image_uri must end in @sha256:<64 lowercase hex characters>."
  }
}

variable "schedule_enabled" {
  description = "Enable the monthly EventBridge Scheduler trigger."
  type        = bool
  default     = false
}

variable "schedule_expression" {
  description = "EventBridge Scheduler expression used only when schedule_enabled is true."
  type        = string
  default     = "cron(0 9 20 * ? *)"
}

variable "schedule_input" {
  description = "Explicit release payload for a scheduled execution."
  type = object({
    source_url      = string
    release_id      = string
    snapshot_month  = string
    expected_sha256 = optional(string)
  })
  default  = null
  nullable = true

  validation {
    condition     = !var.schedule_enabled || var.schedule_input != null
    error_message = "schedule_input is required when schedule_enabled is true."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention for Lambda and Step Functions."
  type        = number
  default     = 30
}

variable "alert_email" {
  description = "Optional email for pipeline alarms and the project cost budget."
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
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than zero."
  }
}
