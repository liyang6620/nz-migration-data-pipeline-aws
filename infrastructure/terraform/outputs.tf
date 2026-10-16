output "data_bucket_name" {
  value       = aws_s3_bucket.pipeline.id
  description = "S3 bucket containing raw, curated, metadata, and query output."
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.pipeline.repository_url
  description = "Push the Lambda container image here before enabling compute."
}

output "glue_database_name" {
  value       = aws_glue_catalog_database.migration.name
  description = "Glue Data Catalog database queried by Athena."
}

output "athena_workgroup_name" {
  value       = aws_athena_workgroup.pipeline.name
  description = "Cost-capped Athena workgroup."
}

output "state_machine_arn" {
  value       = var.deploy_compute ? aws_sfn_state_machine.pipeline[0].arn : null
  description = "Step Functions ARN after compute is enabled."
}
