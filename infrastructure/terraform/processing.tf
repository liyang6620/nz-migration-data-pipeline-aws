resource "aws_cloudwatch_log_group" "glue" {
  name              = "/aws-glue/jobs/${var.project_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_dynamodb_table" "pipeline_runs" {
  name         = "${var.project_name}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"

  attribute {
    name = "idempotency_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_glue_job" "pipeline" {
  name              = "${var.project_name}-migration-arrivals"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = var.glue_worker_type
  number_of_workers = var.glue_number_of_workers
  timeout           = var.glue_timeout_minutes
  max_retries       = 0

  execution_property {
    max_concurrent_runs = 1
  }

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.pipeline.id}/${aws_s3_object.glue_script.key}"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-observability-metrics"     = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.glue.name
    "--TempDir"                          = "s3://${aws_s3_bucket.pipeline.id}/staging/glue-temp/"
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.pipeline.id}/metadata/spark-logs/"
    "--enable-spark-ui"                  = "true"
  }

  depends_on = [
    aws_iam_role_policy.glue,
    aws_s3_object.glue_script,
    aws_s3_object.glue_ruleset,
  ]
}

resource "aws_glue_data_quality_ruleset" "migration_arrivals" {
  name        = "${var.project_name}-migration-arrivals"
  description = "Blocking quality contract for canonical migration arrivals."
  ruleset     = file("${path.module}/../../Glue/rulesets/migration_arrivals.dqdl")

  target_table {
    database_name = aws_glue_catalog_database.migration.name
    table_name    = aws_glue_catalog_table.migration_arrivals.name
  }
}
