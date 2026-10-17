data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue" {
  name               = "${var.project_name}-glue-etl"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
}

data "aws_iam_policy_document" "glue" {
  statement {
    sid       = "ListDataLake"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.pipeline.arn]
  }

  statement {
    sid    = "ReadAndPublishPipelineObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.pipeline.arn}/*"]
  }

  statement {
    sid    = "UseCatalogAndDataQuality"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
      "glue:PublishDataQuality",
      "lakeformation:GetDataAccess",
      "glue:BatchGetPartition",
      "glue:BatchCreatePartition",
      "glue:CreatePartition",
      "glue:UpdatePartition",
      "glue:DeletePartition",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PublishGlueMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "glue" {
  name   = "pipeline-data-access"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue.json
}

data "aws_iam_policy_document" "states_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "states" {
  name               = "${var.project_name}-orchestrator"
  assume_role_policy = data.aws_iam_policy_document.states_assume_role.json
}

data "aws_iam_policy_document" "states" {
  statement {
    sid    = "RunGlueJob"
    effect = "Allow"
    actions = [
      "glue:BatchStopJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:StartJobRun",
    ]
    resources = [aws_glue_job.pipeline.arn]
  }

  statement {
    sid    = "ManageRunRegistry"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
    ]
    resources = [aws_dynamodb_table.pipeline_runs.arn]
  }

  statement {
    sid    = "ValidateWithAthena"
    effect = "Allow"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
    ]
    resources = [aws_athena_workgroup.pipeline.arn]
  }

  statement {
    sid    = "ReadCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
      "lakeformation:GetDataAccess",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadAndCommitPipelineObjects"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      aws_s3_bucket.pipeline.arn,
      "${aws_s3_bucket.pipeline.arn}/${local.athena_result_prefix}*",
      "${aws_s3_bucket.pipeline.arn}/curated/*",
      "${aws_s3_bucket.pipeline.arn}/quality/*",
      "${aws_s3_bucket.pipeline.arn}/staging/commit-candidates/*",
      "${aws_s3_bucket.pipeline.arn}/metadata/commits/*",
      "${aws_s3_bucket.pipeline.arn}/audit/runs/*",
      "${aws_s3_bucket.pipeline.arn}/quarantine/*",
    ]
  }

  statement {
    sid    = "ManageServiceIntegrationRules"
    effect = "Allow"
    actions = [
      "events:DescribeRule",
      "events:PutRule",
      "events:PutTargets",
      "events:RemoveTargets",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForGlueJobsRule"
    ]
  }

  statement {
    sid       = "PublishFailureNotification"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid    = "WriteExecutionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "states" {
  name   = "orchestration-access"
  role   = aws_iam_role.states.id
  policy = data.aws_iam_policy_document.states.json
}

data "aws_iam_policy_document" "pipes_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipes" {
  name               = "${var.project_name}-event-pipe"
  assume_role_policy = data.aws_iam_policy_document.pipes_assume_role.json
}

data "aws_iam_policy_document" "pipes" {
  statement {
    sid    = "ConsumeUploadEvents"
    effect = "Allow"
    actions = [
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.uploads.arn]
  }

  statement {
    sid       = "StartPipeline"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }
}

resource "aws_iam_role_policy" "pipes" {
  name   = "consume-and-start"
  role   = aws_iam_role.pipes.id
  policy = data.aws_iam_policy_document.pipes.json
}

data "aws_iam_policy_document" "consumer_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "analyst" {
  name               = "${var.project_name}-analyst"
  assume_role_policy = data.aws_iam_policy_document.consumer_assume_role.json
}

resource "aws_iam_role" "bi" {
  name               = "${var.project_name}-bi-readonly"
  assume_role_policy = data.aws_iam_policy_document.consumer_assume_role.json
}

data "aws_iam_policy_document" "consumer" {
  statement {
    sid    = "QueryGoldViews"
    effect = "Allow"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
    ]
    resources = [aws_athena_workgroup.pipeline.arn]
  }

  statement {
    sid    = "ReadCatalogAndLakeFormation"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
      "lakeformation:GetDataAccess",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ListApprovedDataPrefixes"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.pipeline.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "curated/*",
        "revisions/*",
        "quality/*",
        "metadata/commits/*",
        "${local.athena_result_prefix}*",
      ]
    }
  }

  statement {
    sid    = "ReadApprovedDataAndUseQueryResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.pipeline.arn}/curated/*",
      "${aws_s3_bucket.pipeline.arn}/revisions/*",
      "${aws_s3_bucket.pipeline.arn}/quality/*",
      "${aws_s3_bucket.pipeline.arn}/metadata/commits/*",
      "${aws_s3_bucket.pipeline.arn}/${local.athena_result_prefix}*",
    ]
  }
}

resource "aws_iam_role_policy" "analyst" {
  name   = "gold-query-access"
  role   = aws_iam_role.analyst.id
  policy = data.aws_iam_policy_document.consumer.json
}

resource "aws_iam_role_policy" "bi" {
  name   = "gold-query-access"
  role   = aws_iam_role.bi.id
  policy = data.aws_iam_policy_document.consumer.json
}
