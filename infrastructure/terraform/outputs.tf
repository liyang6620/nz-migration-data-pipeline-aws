output "data_bucket_name" {
  value       = aws_s3_bucket.pipeline.id
  description = "S3 bucket containing raw, curated, metadata, and query output."
}

output "glue_database_name" {
  value       = aws_glue_catalog_database.migration.name
  description = "Glue Data Catalog database queried by Athena."
}

output "gold_database_name" {
  value       = aws_glue_catalog_database.gold.name
  description = "Consumer-facing Glue database containing governed Gold views."
}

output "athena_workgroup_name" {
  value       = aws_athena_workgroup.pipeline.name
  description = "Cost-capped Athena workgroup."
}

output "state_machine_arn" {
  value       = aws_sfn_state_machine.pipeline.arn
  description = "Event-driven Step Functions orchestration state machine."
}

output "landing_key_template" {
  value       = "${local.landing_prefix}snapshot_month=YYYY-MM/release_id=<release-id>/source.csv"
  description = "Only uploads matching this key contract trigger the pipeline."
}

output "dead_letter_queue_url" {
  value       = aws_sqs_queue.uploads_dlq.url
  description = "Failed event deliveries retained for operator replay."
}

output "analyst_role_arn" {
  value       = aws_iam_role.analyst.arn
  description = "Read-only consumer role for the governed Gold interface."
}

output "bi_role_arn" {
  value       = aws_iam_role.bi.arn
  description = "Read-only BI consumer role for the governed Gold interface."
}
