# Terraform deployment

This stack deploys the complete upload-driven AWS runtime in ap-southeast-2:
S3, EventBridge, SQS FIFO and DLQ, EventBridge Pipes, Step Functions Standard,
DynamoDB, Glue 5.0, Glue Data Quality assets, Glue Catalog, Lake Formation,
Athena Gold views, CloudWatch, SNS, and an AWS Budget.

It does not create a NAT Gateway, VPC, EC2, ECS, Redshift, QuickSight, MWAA,
Lambda, ECR, schedule, or always-on service.

## Safety boundary

- The S3 bucket has force_destroy disabled.
- S3 versioning, managed encryption, public-access blocking, and TLS-only
  access are enabled.
- Glue is capped at two G.1X workers by default, one concurrent run, and a
  15-minute timeout.
- Athena rejects any query that scans more than 1 GB.
- Logs retain 14 days by default.
- The US$3 budget is always created. Email notifications are created only when
  alert_email is set and the subscription is confirmed.
- The budget is an alert and cannot guarantee a hard spending limit.

## Review and deploy

Use an authenticated CLI for the intended personal account:

~~~bash
aws sts get-caller-identity
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform show tfplan
terraform apply tfplan
~~~

Do not apply if the caller account is not the intended account or if the plan
contains an unexpected bucket replacement or data deletion.

The repository intentionally does not configure a remote state backend for
this single-maintainer demo. Terraform state can contain resource identifiers
and must never be committed.

## Variables

| Variable | Default | Purpose |
|---|---:|---|
| aws_region | ap-southeast-2 | Region for the complete runtime |
| project_name | nz-migration-v2 | Resource and cost-tag prefix |
| environment | demo | Deployment environment tag |
| glue_worker_type | G.1X | Bounded Spark worker class |
| glue_number_of_workers | 2 | Minimum bounded Glue capacity |
| glue_timeout_minutes | 15 | Hard per-run timeout |
| log_retention_days | 14 | CloudWatch retention |
| monthly_budget_usd | 3 | Project-tagged monthly budget alert |
| alert_email | null | Optional SNS and Budget subscriber |
| enable_lake_formation | true | Register the lake and grant Gold access |
| lake_formation_admin_principal_arn | null | Dedicated IAM role/user that administers Lake Formation; the Terraform caller is used only as the bootstrap default |

Copy terraform.tfvars.example to an ignored terraform.tfvars only when an
override is required. Do not commit email addresses, credentials, or state.

On the first deployment, Terraform must initialize the account's Lake Formation
administrator before it can issue catalog and data-location grants. When
`lake_formation_admin_principal_arn` is unset, the authenticated Terraform caller
is registered for that bootstrap. For ongoing operations, deploy through a
dedicated IAM role and set this variable to that role's ARN; do not keep using
the account root identity.

## First release

After apply, upload the oldest release first:

~~~bash
aws s3 cp source.csv \
  s3://BUCKET/landing/dataset=migration/snapshot_month=2025-10/release_id=stats-nz-2025-10/source.csv
~~~

Wait for SUCCEEDED before uploading the next month. Validate:

~~~sql
SELECT * FROM nz_migration_v2_gold.vw_release_history
ORDER BY snapshot_month;

SELECT * FROM nz_migration_v2_gold.vw_pipeline_quality
ORDER BY snapshot_month;
~~~

Use the operations runbook for replay, DLQ recovery, quarantine, stale locks,
backfill, and cost incidents.
