resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.project_name}-ingest"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "transform" {
  name              = "/aws/lambda/${var.project_name}-transform"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "states" {
  name              = "/aws/vendedlogs/states/${var.project_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "ingest" {
  count = var.deploy_compute ? 1 : 0

  function_name = "${var.project_name}-ingest"
  role          = aws_iam_role.ingest.arn
  package_type  = "Image"
  image_uri     = var.container_image_uri
  architectures = ["x86_64"]
  memory_size   = 512
  timeout       = 120

  image_config {
    command = ["nz_migration_pipeline.aws_handler.ingest_handler"]
  }

  environment {
    variables = local.common_environment
  }

  reserved_concurrent_executions = 1

  depends_on = [
    aws_cloudwatch_log_group.ingest,
    aws_iam_role_policy.ingest,
  ]
}

resource "aws_lambda_function" "transform" {
  count = var.deploy_compute ? 1 : 0

  function_name = "${var.project_name}-transform"
  role          = aws_iam_role.transform.arn
  package_type  = "Image"
  image_uri     = var.container_image_uri
  architectures = ["x86_64"]
  memory_size   = 1536
  timeout       = 600

  ephemeral_storage {
    size = 2048
  }

  image_config {
    command = ["nz_migration_pipeline.aws_handler.transform_handler"]
  }

  environment {
    variables = local.common_environment
  }

  reserved_concurrent_executions = 1

  depends_on = [
    aws_cloudwatch_log_group.transform,
    aws_iam_role_policy.transform,
  ]
}

resource "aws_sfn_state_machine" "pipeline" {
  count = var.deploy_compute ? 1 : 0

  name     = var.project_name
  role_arn = aws_iam_role.states.arn
  type     = "STANDARD"

  logging_configuration {
    include_execution_data = false
    level                  = "ERROR"
    log_destination        = "${aws_cloudwatch_log_group.states.arn}:*"
  }

  definition = jsonencode({
    Comment = "Ingest and publish one immutable Stats NZ migration snapshot"
    StartAt = "IngestRelease"
    States = {
      IngestRelease = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.ingest[0].arn
          "Payload.$"  = "$"
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Next = "TransformAndPublish"
      }
      TransformAndPublish = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.transform[0].arn
          "Payload.$"  = "$"
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        End = true
      }
    }
  })

  depends_on = [aws_iam_role_policy.states]
}

resource "aws_scheduler_schedule" "monthly" {
  count = var.deploy_compute && var.schedule_enabled ? 1 : 0

  name                         = "${var.project_name}-monthly"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "Pacific/Auckland"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 60
  }

  target {
    arn      = aws_sfn_state_machine.pipeline[0].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode(var.schedule_input)

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  depends_on = [aws_iam_role_policy.scheduler]
}
