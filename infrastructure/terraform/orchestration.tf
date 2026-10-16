resource "aws_cloudwatch_log_group" "states" {
  name              = "/aws/vendedlogs/states/${var.project_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_sqs_queue" "uploads_dlq" {
  name                      = "${var.project_name}-uploads-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "uploads" {
  name                        = "${var.project_name}-uploads.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 345600
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.uploads_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "uploads" {
  queue_url = aws_sqs_queue.uploads_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.uploads.arn]
  })
}

resource "aws_s3_bucket_notification" "pipeline" {
  bucket      = aws_s3_bucket.pipeline.id
  eventbridge = true
}

resource "aws_cloudwatch_event_rule" "landing_upload" {
  name        = "${var.project_name}-landing-upload"
  description = "Accept only contracted migration source uploads."

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = {
        name = [aws_s3_bucket.pipeline.id]
      }
      object = {
        key = [{
          wildcard = "${local.landing_prefix}snapshot_month=*/release_id=*/source.csv"
        }]
      }
    }
  })
}

data "aws_iam_policy_document" "eventbridge_to_uploads" {
  statement {
    sid    = "AllowLandingRule"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.uploads.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.landing_upload.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "uploads" {
  queue_url = aws_sqs_queue.uploads.id
  policy    = data.aws_iam_policy_document.eventbridge_to_uploads.json
}

resource "aws_cloudwatch_event_target" "uploads" {
  rule      = aws_cloudwatch_event_rule.landing_upload.name
  target_id = "buffer-upload"
  arn       = aws_sqs_queue.uploads.arn

  sqs_target {
    message_group_id = "migration"
  }

  depends_on = [aws_sqs_queue_policy.uploads]
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = var.project_name
  role_arn = aws_iam_role.states.arn
  type     = "STANDARD"

  logging_configuration {
    include_execution_data = false
    level                  = "ERROR"
    log_destination        = "${aws_cloudwatch_log_group.states.arn}:*"
  }

  tracing_configuration {
    enabled = false
  }

  definition = jsonencode({
    Comment = "Validate, transform, quality-gate, and commit one migration release"
    StartAt = "NormaliseUpload"
    States = {
      NormaliseUpload = {
        Type = "Pass"
        Parameters = {
          "bucket.$"          = "$.detail.bucket.name"
          "object_key.$"      = "$.detail.object.key"
          "version_id.$"      = "$.detail.object.version-id"
          "event_time.$"      = "$.time"
          "execution_arn.$"   = "$$.Execution.Id"
          "run_id.$"          = "$$.Execution.Name"
          "idempotency_key.$" = "States.Format('{}#{}#{}', $.detail.bucket.name, $.detail.object.key, $.detail.object.version-id)"
        }
        Next = "ValidateUploadContract"
      }
      ValidateUploadContract = {
        Type = "Choice"
        Choices = [{
          And = [
            { Variable = "$.bucket", StringEquals = aws_s3_bucket.pipeline.id },
            { Variable = "$.object_key", StringMatches = "${local.landing_prefix}snapshot_month=*/release_id=*/source.csv" },
          ]
          Next = "ParseReleaseIdentifiers"
        }]
        Default = "RejectInvalidEvent"
      }
      ParseReleaseIdentifiers = {
        Type = "Pass"
        Parameters = {
          "bucket.$"          = "$.bucket"
          "object_key.$"      = "$.object_key"
          "version_id.$"      = "$.version_id"
          "event_time.$"      = "$.event_time"
          "execution_arn.$"   = "$.execution_arn"
          "run_id.$"          = "$.run_id"
          "idempotency_key.$" = "$.idempotency_key"
          "snapshot_month.$"  = "States.ArrayGetItem(States.StringSplit(States.ArrayGetItem(States.StringSplit($.object_key, '/'), 2), '='), 1)"
          "release_id.$"      = "States.ArrayGetItem(States.StringSplit(States.ArrayGetItem(States.StringSplit($.object_key, '/'), 3), '='), 1)"
        }
        Next = "ClaimRun"
      }
      ClaimRun = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:putItem"
        Parameters = {
          TableName = aws_dynamodb_table.pipeline_runs.name
          Item = {
            idempotency_key = { "S.$" = "$.idempotency_key" }
            record_type     = { S = "PIPELINE_RUN" }
            status          = { S = "RECEIVED" }
            bucket          = { "S.$" = "$.bucket" }
            object_key      = { "S.$" = "$.object_key" }
            version_id      = { "S.$" = "$.version_id" }
            snapshot_month  = { "S.$" = "$.snapshot_month" }
            release_id      = { "S.$" = "$.release_id" }
            execution_arn   = { "S.$" = "$.execution_arn" }
            started_at      = { "S.$" = "$$.State.EnteredTime" }
          }
          ConditionExpression = "attribute_not_exists(idempotency_key)"
        }
        ResultPath = null
        Catch = [{
          ErrorEquals = ["DynamoDB.ConditionalCheckFailedException"]
          ResultPath  = "$.duplicate"
          Next        = "ReadExistingRun"
        }]
        Next = "AcquireDatasetLock"
      }
      ReadExistingRun = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:getItem"
        Parameters = {
          TableName = aws_dynamodb_table.pipeline_runs.name
          Key = {
            idempotency_key = { "S.$" = "$.idempotency_key" }
          }
          ConsistentRead = true
        }
        ResultPath = "$.existing"
        Next       = "DecideDuplicateAction"
      }
      DecideDuplicateAction = {
        Type = "Choice"
        Choices = [
          {
            Variable     = "$.existing.Item.status.S"
            StringEquals = "FAILED"
            Next         = "ReopenRun"
          },
          {
            Variable     = "$.existing.Item.status.S"
            StringEquals = "QUARANTINED"
            Next         = "ReopenRun"
          },
        ]
        Default = "DuplicateDelivery"
      }
      ReopenRun = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName = aws_dynamodb_table.pipeline_runs.name
          Key = {
            idempotency_key = { "S.$" = "$.idempotency_key" }
          }
          UpdateExpression         = "SET #status = :status, execution_arn = :execution_arn, started_at = :started_at REMOVE completed_at, error_detail"
          ConditionExpression      = "#status IN (:failed, :quarantined)"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"        = { S = "RECEIVED" }
            ":failed"        = { S = "FAILED" }
            ":quarantined"   = { S = "QUARANTINED" }
            ":execution_arn" = { "S.$" = "$.execution_arn" }
            ":started_at"    = { "S.$" = "$$.State.EnteredTime" }
          }
        }
        ResultPath = null
        Next       = "AcquireDatasetLock"
      }
      DuplicateDelivery = {
        Type    = "Succeed"
        Comment = "A successful or active delivery already has a durable run record."
      }
      AcquireDatasetLock = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:putItem"
        Parameters = {
          TableName = aws_dynamodb_table.pipeline_runs.name
          Item = {
            idempotency_key = { S = "LOCK#migration" }
            record_type     = { S = "DATASET_LOCK" }
            holder          = { "S.$" = "$.execution_arn" }
            acquired_at     = { "S.$" = "$$.State.EnteredTime" }
          }
          ConditionExpression = "attribute_not_exists(idempotency_key)"
        }
        ResultPath = null
        Retry = [{
          ErrorEquals     = ["DynamoDB.ConditionalCheckFailedException"]
          IntervalSeconds = 20
          MaxAttempts     = 45
          BackoffRate     = 1
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "MarkLockUnavailable"
        }]
        Next = "MarkTransforming"
      }
      MarkTransforming = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName = aws_dynamodb_table.pipeline_runs.name
          Key = {
            idempotency_key = { "S.$" = "$.idempotency_key" }
          }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"     = { S = "TRANSFORMING" }
            ":updated_at" = { "S.$" = "$$.State.EnteredTime" }
          }
        }
        ResultPath = null
        Next       = "RunGlueETL"
      }
      RunGlueETL = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = aws_glue_job.pipeline.name
          Arguments = {
            "--SOURCE_BUCKET.$"     = "$.bucket"
            "--SOURCE_KEY.$"        = "$.object_key"
            "--SOURCE_VERSION_ID.$" = "$.version_id"
            "--RUN_ID.$"            = "$.run_id"
            "--DATA_BUCKET"         = aws_s3_bucket.pipeline.id
            "--DQ_RULESET_S3_URI"   = "s3://${aws_s3_bucket.pipeline.id}/${aws_s3_object.glue_ruleset.key}"
          }
        }
        ResultPath = "$.glue"
        Retry = [{
          ErrorEquals     = ["Glue.ConcurrentRunsExceededException", "Glue.OperationTimeoutException", "Glue.InternalServiceException", "Glue.ThrottlingException"]
          IntervalSeconds = 30
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "ClassifyGlueFailure"
        }]
        Next = "MarkQualityCheck"
      }
      ClassifyGlueFailure = {
        Type = "Choice"
        Choices = [{
          Variable      = "$.error.Cause"
          StringMatches = "*DataContractError*"
          Next          = "WriteQuarantineRecord"
        }]
        Default = "MarkFailed"
      }
      WriteQuarantineRecord = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::aws-sdk:s3:putObject"
        Parameters = {
          Bucket      = aws_s3_bucket.pipeline.id
          "Key.$"     = "States.Format('quarantine/snapshot_month={}/release_id={}/{}.json', $.snapshot_month, $.release_id, $.run_id)"
          "Body.$"    = "States.JsonToString($.error)"
          ContentType = "application/json"
        }
        ResultPath = null
        Next       = "MarkQuarantined"
      }
      MarkQualityCheck = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName                = aws_dynamodb_table.pipeline_runs.name
          Key                      = { idempotency_key = { "S.$" = "$.idempotency_key" } }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"     = { S = "QUALITY_CHECK" }
            ":updated_at" = { "S.$" = "$$.State.EnteredTime" }
          }
        }
        ResultPath = null
        Next       = "ValidateCuratedOutput"
      }
      ValidateCuratedOutput = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::athena:startQueryExecution.sync"
        Parameters = {
          "QueryString.$" = "States.Format('SELECT IF(COUNT(*) > 0 AND COUNT_IF(metric_slice = \\'total\\') = COUNT(DISTINCT year_month), COUNT(*), CAST(\\'invalid canonical output\\' AS BIGINT)) AS validated_rows FROM ${aws_glue_catalog_database.migration.name}.migration_arrivals WHERE snapshot_month = \\'{}\\'', $.snapshot_month)"
          WorkGroup       = aws_athena_workgroup.pipeline.name
          QueryExecutionContext = {
            Database = aws_glue_catalog_database.migration.name
          }
        }
        ResultPath = "$.athena_curated"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "MarkFailed"
        }]
        Next = "ValidateQualityEvidence"
      }
      ValidateQualityEvidence = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::athena:startQueryExecution.sync"
        Parameters = {
          "QueryString.$" = "States.Format('SELECT IF(COUNT(*) = 1 AND MAX(quality_status) = \\'passed\\', 1, CAST(\\'quality gate failed\\' AS BIGINT)) AS quality_gate FROM ${aws_glue_catalog_database.migration.name}.pipeline_quality WHERE snapshot_month = \\'{}\\'', $.snapshot_month)"
          WorkGroup       = aws_athena_workgroup.pipeline.name
          QueryExecutionContext = {
            Database = aws_glue_catalog_database.migration.name
          }
        }
        ResultPath = "$.athena_quality"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "MarkFailed"
        }]
        Next = "BuildCommitMarker"
      }
      BuildCommitMarker = {
        Type = "Pass"
        Parameters = {
          "release_id.$"     = "$.release_id"
          "run_id.$"         = "$.run_id"
          "snapshot_month.$" = "$.snapshot_month"
          status             = "SUCCEEDED"
          "committed_at.$"   = "$$.State.EnteredTime"
        }
        ResultPath = "$.commit"
        Next       = "PublishCommitMarker"
      }
      PublishCommitMarker = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::aws-sdk:s3:putObject"
        Parameters = {
          Bucket      = aws_s3_bucket.pipeline.id
          "Key.$"     = "States.Format('metadata/commits/snapshot_month={}/success.json', $.snapshot_month)"
          "Body.$"    = "States.JsonToString($.commit)"
          ContentType = "application/json"
        }
        ResultPath = null
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "MarkFailed"
        }]
        Next = "MarkSucceeded"
      }
      MarkSucceeded = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName                = aws_dynamodb_table.pipeline_runs.name
          Key                      = { idempotency_key = { "S.$" = "$.idempotency_key" } }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at, completed_at = :completed_at"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"       = { S = "SUCCEEDED" }
            ":updated_at"   = { "S.$" = "$$.State.EnteredTime" }
            ":completed_at" = { "S.$" = "$$.State.EnteredTime" }
          }
        }
        ResultPath = null
        Next       = "WriteSuccessAudit"
      }
      WriteSuccessAudit = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::aws-sdk:s3:putObject"
        Parameters = {
          Bucket      = aws_s3_bucket.pipeline.id
          "Key.$"     = "States.Format('audit/runs/{}.json', $.run_id)"
          "Body.$"    = "States.JsonToString($.commit)"
          ContentType = "application/json"
        }
        ResultPath = null
        Next       = "ReleaseLockAfterSuccess"
      }
      ReleaseLockAfterSuccess = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:deleteItem"
        Parameters = {
          TableName           = aws_dynamodb_table.pipeline_runs.name
          Key                 = { idempotency_key = { S = "LOCK#migration" } }
          ConditionExpression = "holder = :holder"
          ExpressionAttributeValues = {
            ":holder" = { "S.$" = "$.execution_arn" }
          }
        }
        ResultPath = null
        End        = true
      }
      MarkQuarantined = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName                = aws_dynamodb_table.pipeline_runs.name
          Key                      = { idempotency_key = { "S.$" = "$.idempotency_key" } }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at, error_detail = :error"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"     = { S = "QUARANTINED" }
            ":updated_at" = { "S.$" = "$$.State.EnteredTime" }
            ":error"      = { "S.$" = "States.JsonToString($.error)" }
          }
        }
        ResultPath = null
        Next       = "WriteFailureAudit"
      }
      MarkFailed = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName                = aws_dynamodb_table.pipeline_runs.name
          Key                      = { idempotency_key = { "S.$" = "$.idempotency_key" } }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at, error_detail = :error"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"     = { S = "FAILED" }
            ":updated_at" = { "S.$" = "$$.State.EnteredTime" }
            ":error"      = { "S.$" = "States.JsonToString($.error)" }
          }
        }
        ResultPath = null
        Next       = "WriteFailureAudit"
      }
      WriteFailureAudit = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::aws-sdk:s3:putObject"
        Parameters = {
          Bucket      = aws_s3_bucket.pipeline.id
          "Key.$"     = "States.Format('audit/runs/{}-failure.json', $.run_id)"
          "Body.$"    = "States.JsonToString($.error)"
          ContentType = "application/json"
        }
        ResultPath = null
        Next       = "ReleaseLockAfterFailure"
      }
      ReleaseLockAfterFailure = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:deleteItem"
        Parameters = {
          TableName           = aws_dynamodb_table.pipeline_runs.name
          Key                 = { idempotency_key = { S = "LOCK#migration" } }
          ConditionExpression = "holder = :holder"
          ExpressionAttributeValues = {
            ":holder" = { "S.$" = "$.execution_arn" }
          }
        }
        ResultPath = null
        Next       = "NotifyFailure"
      }
      MarkLockUnavailable = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::dynamodb:updateItem"
        Parameters = {
          TableName                = aws_dynamodb_table.pipeline_runs.name
          Key                      = { idempotency_key = { "S.$" = "$.idempotency_key" } }
          UpdateExpression         = "SET #status = :status, updated_at = :updated_at, error_detail = :error"
          ExpressionAttributeNames = { "#status" = "status" }
          ExpressionAttributeValues = {
            ":status"     = { S = "FAILED" }
            ":updated_at" = { "S.$" = "$$.State.EnteredTime" }
            ":error"      = { "S.$" = "States.JsonToString($.error)" }
          }
        }
        ResultPath = null
        Next       = "NotifyFailure"
      }
      NotifyFailure = {
        Type     = "Task"
        Resource = "arn:${data.aws_partition.current.partition}:states:::sns:publish"
        Parameters = {
          TopicArn    = local.alerts_topic_arn
          Subject     = "NZ migration pipeline failure"
          "Message.$" = "States.Format('Run {} for release {} failed. Inspect Step Functions execution {}.', $.run_id, $.release_id, $.execution_arn)"
        }
        ResultPath = null
        Next       = "PipelineFailed"
      }
      RejectInvalidEvent = {
        Type  = "Fail"
        Error = "InvalidUploadEvent"
        Cause = "The event did not match the contracted bucket and landing key."
      }
      PipelineFailed = {
        Type  = "Fail"
        Error = "PipelineRunFailed"
        Cause = "The run failed or was quarantined; inspect the registry and audit record."
      }
    }
  })

  depends_on = [aws_iam_role_policy.states]
}

resource "aws_pipes_pipe" "uploads" {
  name          = "${var.project_name}-uploads"
  role_arn      = aws_iam_role.pipes.arn
  source        = aws_sqs_queue.uploads.arn
  target        = aws_sfn_state_machine.pipeline.arn
  desired_state = "RUNNING"

  source_parameters {
    sqs_queue_parameters {
      batch_size                         = 1
      maximum_batching_window_in_seconds = 0
    }
  }

  target_parameters {
    input_template = "<$.body>"

    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }
}
