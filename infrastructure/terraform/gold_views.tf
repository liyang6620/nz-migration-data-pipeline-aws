locals {
  fact_projection = join(", ", [
    for column in local.fact_columns : "facts.${column.name}"
  ])

  committed_facts_sql = <<-SQL
    SELECT ${local.fact_projection}
    FROM ${local.catalog_database}.migration_arrivals AS facts
    INNER JOIN ${local.catalog_database}.release_commits AS commits
      ON facts.snapshot_month = commits.snapshot_month
    WHERE commits.status = 'SUCCEEDED'
  SQL

  latest_facts_sql = <<-SQL
    WITH committed_facts AS (
      ${local.committed_facts_sql}
    ),
    latest AS (
      SELECT max(snapshot_month) AS snapshot_month
      FROM committed_facts
    )
    SELECT facts.*
    FROM committed_facts AS facts
    INNER JOIN latest
      ON facts.snapshot_month = latest.snapshot_month
  SQL

  fact_columns = [
    { name = "release_id", type = "varchar" },
    { name = "source_release_month", type = "varchar" },
    { name = "passenger_type", type = "varchar" },
    { name = "direction", type = "varchar" },
    { name = "citizenship", type = "varchar" },
    { name = "visa", type = "varchar" },
    { name = "country_of_residence", type = "varchar" },
    { name = "metric_slice", type = "varchar" },
    { name = "estimate", type = "bigint" },
    { name = "standard_error", type = "double" },
    { name = "status", type = "varchar" },
    { name = "source_sha256", type = "varchar" },
    { name = "ingested_at", type = "varchar" },
    { name = "schema_version", type = "varchar" },
    { name = "snapshot_month", type = "varchar" },
    { name = "year_month", type = "varchar" },
  ]

  gold_views = {
    vw_latest_monthly_arrivals = {
      sql     = local.latest_facts_sql
      columns = local.fact_columns
    }
    vw_total_arrivals = {
      sql = <<-SQL
        SELECT snapshot_month, release_id, year_month, estimate AS arrivals,
               standard_error, status
        FROM ${local.gold_database}.vw_latest_monthly_arrivals
        WHERE metric_slice = 'total'
      SQL
      columns = [
        { name = "snapshot_month", type = "varchar" },
        { name = "release_id", type = "varchar" },
        { name = "year_month", type = "varchar" },
        { name = "arrivals", type = "bigint" },
        { name = "standard_error", type = "double" },
        { name = "status", type = "varchar" },
      ]
    }
    vw_arrivals_by_citizenship = {
      sql = <<-SQL
        SELECT snapshot_month, release_id, year_month, citizenship,
               estimate AS arrivals, standard_error, status
        FROM ${local.gold_database}.vw_latest_monthly_arrivals
        WHERE metric_slice = 'citizenship'
      SQL
      columns = [
        { name = "snapshot_month", type = "varchar" },
        { name = "release_id", type = "varchar" },
        { name = "year_month", type = "varchar" },
        { name = "citizenship", type = "varchar" },
        { name = "arrivals", type = "bigint" },
        { name = "standard_error", type = "double" },
        { name = "status", type = "varchar" },
      ]
    }
    vw_arrivals_by_visa = {
      sql = <<-SQL
        SELECT snapshot_month, release_id, year_month, visa,
               estimate AS arrivals, standard_error, status
        FROM ${local.gold_database}.vw_latest_monthly_arrivals
        WHERE metric_slice = 'visa'
      SQL
      columns = [
        { name = "snapshot_month", type = "varchar" },
        { name = "release_id", type = "varchar" },
        { name = "year_month", type = "varchar" },
        { name = "visa", type = "varchar" },
        { name = "arrivals", type = "bigint" },
        { name = "standard_error", type = "double" },
        { name = "status", type = "varchar" },
      ]
    }
    vw_revision_summary = {
      sql = <<-SQL
        SELECT revisions.current_snapshot, revisions.previous_snapshot,
               count_if(change_type = 'added') AS added_facts,
               count_if(change_type = 'removed') AS removed_facts,
               count_if(change_type = 'revised') AS revised_facts,
               count_if(change_type = 'unchanged') AS unchanged_facts,
               sum(CASE WHEN change_type = 'revised' THEN estimate_delta ELSE 0 END)
                 AS net_revised_estimate
        FROM ${local.catalog_database}.migration_revisions AS revisions
        INNER JOIN ${local.catalog_database}.release_commits AS commits
          ON revisions.current_snapshot = commits.snapshot_month
        WHERE commits.status = 'SUCCEEDED'
        GROUP BY 1, 2
      SQL
      columns = [
        { name = "current_snapshot", type = "varchar" },
        { name = "previous_snapshot", type = "varchar" },
        { name = "added_facts", type = "bigint" },
        { name = "removed_facts", type = "bigint" },
        { name = "revised_facts", type = "bigint" },
        { name = "unchanged_facts", type = "bigint" },
        { name = "net_revised_estimate", type = "bigint" },
      ]
    }
    vw_release_history = {
      sql = <<-SQL
        SELECT commits.snapshot_month, commits.release_id, commits.run_id,
               commits.status, commits.committed_at, quality.row_count,
               quality.activity_month_min, quality.activity_month_max,
               quality.schema_version
        FROM ${local.catalog_database}.release_commits AS commits
        LEFT JOIN ${local.catalog_database}.pipeline_quality AS quality
          ON commits.snapshot_month = quality.snapshot_month
        WHERE commits.status = 'SUCCEEDED'
      SQL
      columns = [
        { name = "snapshot_month", type = "varchar" },
        { name = "release_id", type = "varchar" },
        { name = "run_id", type = "varchar" },
        { name = "status", type = "varchar" },
        { name = "committed_at", type = "varchar" },
        { name = "row_count", type = "bigint" },
        { name = "activity_month_min", type = "varchar" },
        { name = "activity_month_max", type = "varchar" },
        { name = "schema_version", type = "varchar" },
      ]
    }
    vw_pipeline_quality = {
      sql = <<-SQL
        SELECT quality.snapshot_month, quality.release_id,
               quality.quality_status, quality.row_count,
               quality.activity_month_min, quality.activity_month_max,
               quality.schema_version
        FROM ${local.catalog_database}.pipeline_quality AS quality
        INNER JOIN ${local.catalog_database}.release_commits AS commits
          ON quality.snapshot_month = commits.snapshot_month
        WHERE commits.status = 'SUCCEEDED'
      SQL
      columns = [
        { name = "snapshot_month", type = "varchar" },
        { name = "release_id", type = "varchar" },
        { name = "quality_status", type = "varchar" },
        { name = "row_count", type = "bigint" },
        { name = "activity_month_min", type = "varchar" },
        { name = "activity_month_max", type = "varchar" },
        { name = "schema_version", type = "varchar" },
      ]
    }
  }
}

resource "aws_glue_catalog_table" "gold_views" {
  for_each = local.gold_views

  name          = each.key
  database_name = aws_glue_catalog_database.gold.name
  table_type    = "VIRTUAL_VIEW"

  parameters = {
    presto_view = "true"
  }

  storage_descriptor {
    dynamic "columns" {
      for_each = each.value.columns

      content {
        name = columns.value.name
        type = columns.value.type == "varchar" ? "string" : columns.value.type
      }
    }
  }

  view_original_text = format("/* Presto View: %s */", base64encode(jsonencode({
    originalSql  = trimspace(each.value.sql)
    catalog      = "awsdatacatalog"
    schema       = local.gold_database
    columns      = each.value.columns
    owner        = data.aws_caller_identity.current.arn
    runAsInvoker = false
  })))
  view_expanded_text = "/* Presto View */"

  depends_on = [
    aws_glue_catalog_table.migration_arrivals,
    aws_glue_catalog_table.migration_revisions,
    aws_glue_catalog_table.pipeline_quality,
    aws_glue_catalog_table.release_commits,
  ]
}
