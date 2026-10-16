data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "${var.project_name}-ingest"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role" "transform" {
  name               = "${var.project_name}-transform"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid       = "ListPipelineBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.pipeline.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["raw/*"]
    }
  }

  statement {
    sid    = "WriteImmutableRawRelease"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.pipeline.arn}/raw/*"]
  }

  statement {
    sid       = "WriteIngestQuarantine"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.pipeline.arn}/quarantine/ingest/*"]
  }

  statement {
    sid    = "WriteIngestLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "pipeline-access"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

data "aws_iam_policy_document" "transform" {
  statement {
    sid       = "ListPipelineData"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.pipeline.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "raw/*",
        "curated/*",
        "metadata/*",
        "quarantine/*",
        "staging/*",
      ]
    }
  }

  statement {
    sid    = "ReadRawAndCuratedData"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.pipeline.arn}/raw/*",
      "${aws_s3_bucket.pipeline.arn}/curated/*",
      "${aws_s3_bucket.pipeline.arn}/metadata/*",
      "${aws_s3_bucket.pipeline.arn}/staging/*",
    ]
  }

  statement {
    sid    = "PublishPipelineOutputs"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      "${aws_s3_bucket.pipeline.arn}/curated/*",
      "${aws_s3_bucket.pipeline.arn}/metadata/*",
      "${aws_s3_bucket.pipeline.arn}/quarantine/*",
      "${aws_s3_bucket.pipeline.arn}/staging/*",
    ]
  }

  statement {
    sid    = "WriteTransformLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.transform.arn}:*"]
  }
}

resource "aws_iam_role_policy" "transform" {
  name   = "pipeline-access"
  role   = aws_iam_role.transform.id
  policy = data.aws_iam_policy_document.transform.json
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
  dynamic "statement" {
    for_each = var.deploy_compute ? [1] : []
    content {
      sid       = "InvokePipelineFunctions"
      effect    = "Allow"
      actions   = ["lambda:InvokeFunction"]
      resources = [aws_lambda_function.ingest[0].arn, aws_lambda_function.transform[0].arn]
    }
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

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler" {
  count = var.deploy_compute ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline[0].arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.deploy_compute ? 1 : 0

  name   = "start-pipeline"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler[0].json
}
