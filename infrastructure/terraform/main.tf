locals {
  bucket_name          = "${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  catalog_database     = replace(var.project_name, "-", "_")
  gold_database        = "${replace(var.project_name, "-", "_")}_gold"
  glue_script_key      = "artifacts/glue/process_migration.py"
  glue_ruleset_key     = "artifacts/glue/migration_arrivals.dqdl"
  landing_prefix       = "landing/dataset=migration/"
  athena_result_prefix = "metadata/athena-results/"
}

resource "aws_s3_bucket" "pipeline" {
  bucket        = local.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-abandoned-staging"
    status = "Enabled"

    filter {
      prefix = "staging/"
    }

    expiration {
      days = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  rule {
    id     = "expire-landing-copies"
    status = "Enabled"

    filter {
      prefix = "landing/"
    }

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.pipeline]
}

data "aws_iam_policy_document" "require_tls" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.pipeline.arn,
      "${aws_s3_bucket.pipeline.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id
  policy = data.aws_iam_policy_document.require_tls.json
}

resource "aws_s3_object" "glue_script" {
  bucket       = aws_s3_bucket.pipeline.id
  key          = local.glue_script_key
  source       = "${path.module}/../../glue/jobs/process_migration.py"
  etag         = filemd5("${path.module}/../../glue/jobs/process_migration.py")
  content_type = "text/x-python"
}

resource "aws_s3_object" "glue_ruleset" {
  bucket       = aws_s3_bucket.pipeline.id
  key          = local.glue_ruleset_key
  source       = "${path.module}/../../glue/rulesets/migration_arrivals.dqdl"
  etag         = filemd5("${path.module}/../../glue/rulesets/migration_arrivals.dqdl")
  content_type = "text/plain"
}

resource "aws_glue_catalog_database" "migration" {
  name        = local.catalog_database
  description = "Silver data contracts for immutable NZ migration snapshots"
}

resource "aws_glue_catalog_database" "gold" {
  name        = local.gold_database
  description = "Stable consumer-facing semantic views"
}

resource "aws_glue_catalog_table" "migration_arrivals" {
  name          = "migration_arrivals"
  database_name = aws_glue_catalog_database.migration.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                            = "parquet"
    "projection.enabled"                      = "true"
    "projection.snapshot_month.type"          = "date"
    "projection.snapshot_month.format"        = "yyyy-MM"
    "projection.snapshot_month.range"         = "2025-01,NOW"
    "projection.snapshot_month.interval"      = "1"
    "projection.snapshot_month.interval.unit" = "MONTHS"
    "projection.year_month.type"              = "date"
    "projection.year_month.format"            = "yyyy-MM"
    "projection.year_month.range"             = "2001-01,NOW"
    "projection.year_month.interval"          = "1"
    "projection.year_month.interval.unit"     = "MONTHS"
    "storage.location.template"               = "s3://${aws_s3_bucket.pipeline.id}/curated/migration_arrivals/snapshot_month=$${snapshot_month}/year_month=$${year_month}/"
  }

  partition_keys {
    name = "snapshot_month"
    type = "string"
  }

  partition_keys {
    name = "year_month"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.pipeline.id}/curated/migration_arrivals/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = {
        release_id           = "string"
        source_release_month = "string"
        passenger_type       = "string"
        direction            = "string"
        citizenship          = "string"
        visa                 = "string"
        country_of_residence = "string"
        metric_slice         = "string"
        estimate             = "bigint"
        standard_error       = "double"
        status               = "string"
        source_sha256        = "string"
        ingested_at          = "string"
        schema_version       = "string"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_glue_catalog_table" "release_commits" {
  name          = "release_commits"
  database_name = aws_glue_catalog_database.migration.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                            = "json"
    "projection.enabled"                      = "true"
    "projection.snapshot_month.type"          = "date"
    "projection.snapshot_month.format"        = "yyyy-MM"
    "projection.snapshot_month.range"         = "2025-01,NOW"
    "projection.snapshot_month.interval"      = "1"
    "projection.snapshot_month.interval.unit" = "MONTHS"
    "storage.location.template"               = "s3://${aws_s3_bucket.pipeline.id}/metadata/commits/snapshot_month=$${snapshot_month}/"
  }

  partition_keys {
    name = "snapshot_month"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.pipeline.id}/metadata/commits/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    columns {
      name = "release_id"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "run_id"
      type = "string"
    }
    columns {
      name = "committed_at"
      type = "string"
    }
    columns {
      name = "source_sha256"
      type = "string"
    }
    columns {
      name = "row_count"
      type = "bigint"
    }

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
  }
}

resource "aws_glue_catalog_table" "pipeline_quality" {
  name          = "pipeline_quality"
  database_name = aws_glue_catalog_database.migration.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                            = "json"
    "projection.enabled"                      = "true"
    "projection.snapshot_month.type"          = "date"
    "projection.snapshot_month.format"        = "yyyy-MM"
    "projection.snapshot_month.range"         = "2025-01,NOW"
    "projection.snapshot_month.interval"      = "1"
    "projection.snapshot_month.interval.unit" = "MONTHS"
    "storage.location.template"               = "s3://${aws_s3_bucket.pipeline.id}/quality/snapshot_month=$${snapshot_month}/"
  }

  partition_keys {
    name = "snapshot_month"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.pipeline.id}/quality/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    dynamic "columns" {
      for_each = {
        release_id         = "string"
        quality_status     = "string"
        row_count          = "bigint"
        activity_month_min = "string"
        activity_month_max = "string"
        schema_version     = "string"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
  }
}

resource "aws_glue_catalog_table" "migration_revisions" {
  name          = "migration_revisions"
  database_name = aws_glue_catalog_database.migration.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                               = "parquet"
    "projection.enabled"                         = "true"
    "projection.current_snapshot.type"           = "date"
    "projection.current_snapshot.format"         = "yyyy-MM"
    "projection.current_snapshot.range"          = "2025-01,NOW"
    "projection.current_snapshot.interval"       = "1"
    "projection.current_snapshot.interval.unit"  = "MONTHS"
    "projection.previous_snapshot.type"          = "date"
    "projection.previous_snapshot.format"        = "yyyy-MM"
    "projection.previous_snapshot.range"         = "2025-01,NOW"
    "projection.previous_snapshot.interval"      = "1"
    "projection.previous_snapshot.interval.unit" = "MONTHS"
    "storage.location.template"                  = "s3://${aws_s3_bucket.pipeline.id}/revisions/current_snapshot=$${current_snapshot}/previous_snapshot=$${previous_snapshot}/"
  }

  partition_keys {
    name = "current_snapshot"
    type = "string"
  }

  partition_keys {
    name = "previous_snapshot"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.pipeline.id}/revisions/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = merge(
        { for name in [
          "year_month", "passenger_type", "direction", "citizenship", "visa",
          "country_of_residence", "previous_source_release_month",
          "previous_metric_slice", "previous_status", "current_source_release_month",
          "current_metric_slice", "current_status", "change_type"
        ] : name => "string" },
        { for name in [
          "previous_standard_error", "current_standard_error", "standard_error_delta"
        ] : name => "double" },
        { for name in [
          "previous_estimate", "current_estimate", "estimate_delta"
        ] : name => "bigint" }
      )
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_athena_workgroup" "pipeline" {
  name          = var.project_name
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824

    result_configuration {
      output_location = "s3://${aws_s3_bucket.pipeline.id}/${local.athena_result_prefix}"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
