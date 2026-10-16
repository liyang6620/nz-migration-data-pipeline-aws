locals {
  bucket_name = "${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  common_environment = {
    DATA_BUCKET = aws_s3_bucket.pipeline.id
    LOG_LEVEL   = "INFO"
  }
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

resource "aws_ecr_repository" "pipeline" {
  name                 = var.project_name
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "pipeline" {
  repository = aws_ecr_repository.pipeline.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain the five newest images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_glue_catalog_database" "migration" {
  name        = replace(var.project_name, "-", "_")
  description = "Catalog for immutable NZ migration snapshots"
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

resource "aws_athena_workgroup" "pipeline" {
  name          = var.project_name
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824

    result_configuration {
      output_location = "s3://${aws_s3_bucket.pipeline.id}/metadata/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
