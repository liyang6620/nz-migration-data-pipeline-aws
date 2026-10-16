# Terraform deployment

This stack replaces the legacy Glue Spark job with a low-volume serverless
design: S3, two image-based Lambda functions, Step Functions, Glue Data Catalog,
Athena, and an optional EventBridge Scheduler trigger.

No NAT Gateway, VPC, EC2, ECS, Redshift, QuickSight, Glue Spark, or always-on
compute is created. `deploy_compute` and `schedule_enabled` both default to
`false` so an initial plan cannot start recurring workloads.

Setting `alert_email` creates Lambda and Step Functions failure alarms plus a
project-tagged monthly AWS Budget. The email subscription must be confirmed.
For tag-filtered budget data to appear, activate the `Project` cost allocation
tag once in the Billing console. The default budget is US$3 per month.

## Deployment sequence

1. Authenticate the AWS CLI to the intended personal account and verify the
   account ID with `aws sts get-caller-identity`.
2. Run `terraform init`, `terraform plan`, and `terraform apply` with the default
   `deploy_compute = false`. This creates storage, ECR, catalog, and Athena.
3. Build and push the repository's Lambda container image to the
   `ecr_repository_url` output.
4. Resolve the pushed image digest and set `container_image_uri` using the
   immutable `repository@sha256:...` form.
5. Set `deploy_compute = true`, review a second plan, and apply.
6. Keep `schedule_enabled = false` until a manual Step Functions execution has
   processed and queried a real release successfully.

Terraform intentionally does not configure a remote state backend for this
single-maintainer portfolio deployment. The local state file contains resource
identifiers and must never be committed.
