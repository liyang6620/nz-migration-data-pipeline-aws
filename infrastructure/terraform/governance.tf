resource "aws_lakeformation_resource" "pipeline" {
  count = var.enable_lake_formation ? 1 : 0

  arn                     = aws_s3_bucket.pipeline.arn
  use_service_linked_role = true
}

resource "aws_lakeformation_permissions" "glue_data_location" {
  count = var.enable_lake_formation ? 1 : 0

  principal   = aws_iam_role.glue.arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = aws_lakeformation_resource.pipeline[0].arn
  }
}

resource "aws_lakeformation_permissions" "consumer_database" {
  for_each = var.enable_lake_formation ? {
    analyst = aws_iam_role.analyst.arn
    bi      = aws_iam_role.bi.arn
  } : {}

  principal   = each.value
  permissions = ["DESCRIBE"]

  database {
    name = aws_glue_catalog_database.gold.name
  }
}

resource "aws_lakeformation_permissions" "orchestrator_database" {
  count = var.enable_lake_formation ? 1 : 0

  principal   = aws_iam_role.states.arn
  permissions = ["DESCRIBE"]

  database {
    name = aws_glue_catalog_database.migration.name
  }
}

resource "aws_lakeformation_permissions" "orchestrator_tables" {
  for_each = var.enable_lake_formation ? toset([
    aws_glue_catalog_table.migration_arrivals.name,
    aws_glue_catalog_table.pipeline_quality.name,
  ]) : toset([])

  principal   = aws_iam_role.states.arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.migration.name
    name          = each.value
  }
}

resource "aws_lakeformation_permissions" "consumer_views" {
  for_each = var.enable_lake_formation ? {
    analyst = aws_iam_role.analyst.arn
    bi      = aws_iam_role.bi.arn
  } : {}

  principal   = each.value
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.gold.name
    wildcard      = true
  }

  depends_on = [aws_glue_catalog_table.gold_views]
}
