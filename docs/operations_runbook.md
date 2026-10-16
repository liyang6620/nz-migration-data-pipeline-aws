# Operations runbook

## Normal release

1. Confirm the CSV publisher, release month, file size, and checksum.
2. Upload the file to the contracted landing key. Upload the oldest missing
   snapshot first.
3. Confirm one Step Functions execution started.
4. Check the DynamoDB run record progresses through TRANSFORMING and
   QUALITY_CHECK to SUCCEEDED.
5. Confirm the commit marker exists under the snapshot month.
6. Query vw_release_history and vw_pipeline_quality in the managed Athena
   workgroup.
7. For releases after the first, query vw_revision_summary and review unusually
   large revision counts.

## Failure triage

Start with the Step Functions execution and DynamoDB run record:

- QUARANTINED means the source or data quality contract failed. Inspect the
  quarantine JSON and Glue logs. Do not publish or manually create a commit.
- FAILED before Glue normally indicates IAM, service availability, lock, or
  orchestration failure.
- FAILED after Glue normally indicates Athena validation, commit publication,
  or audit failure.
- A message in the DLQ means Pipes could not deliver the event to Step
  Functions after repeated attempts. It does not represent an ETL failure.

The Gold views join commit markers, so failed and partially copied snapshots
remain invisible to consumers.

## Replay a failed or quarantined run

Use the original EventBridge event as input to a new execution of the same
state machine. The original bucket, object key, and object version ID must be
unchanged. The state machine reopens only FAILED or QUARANTINED registry
records. SUCCEEDED and active records are treated as duplicate delivery.

Do not delete the prior run record. It is part of the audit trail.

## DLQ recovery

1. Inspect the DLQ message and verify its bucket, key, and version ID.
2. Resolve the target, IAM, quota, or state machine issue.
3. Use SQS redrive to move only verified messages back to the source queue.
4. Confirm the new execution and that the DLQ returns to zero.

## Stale dataset lock

The lock item key is LOCK#migration. It should exist only while one execution
owns publication.

Before removing a stale lock:

1. Confirm no execution with the recorded holder ARN is RUNNING.
2. Confirm no Glue run for the project is RUNNING or STOPPING.
3. Record the reason and holder ARN in the incident notes.
4. Delete only the LOCK#migration item.
5. Replay the failed event.

Never remove the lock merely because a second upload is waiting.

## Historical backfill

- Process snapshots in chronological order so revision comparisons use the
  immediately preceding committed snapshot.
- Use one distinct release_id per official release.
- Wait for SUCCEEDED before uploading the next month.
- Verify row counts and activity ranges after each commit.

The current contract permits one committed release per snapshot month.
Replacing a committed month is a governed breaking operation and is not an
ordinary replay.

## Rollback

Terraform rollback reverts infrastructure only; it does not delete the data
bucket. Do not use force destruction. If a bad release was committed, disable
consumer access, preserve all evidence, and use a reviewed data correction
procedure. Never overwrite or delete raw provenance to make a dashboard look
correct.

## Cost response

The US$3 budget is an alert, not a hard limit. If the forecast exceeds the
threshold:

1. Stop uploading new releases.
2. Check Glue duration and run count by tag.
3. Check Athena scanned bytes and unexpected workgroup users.
4. Check S3 growth in staging, Spark logs, and query results.
5. Fix the cause before resuming backfills.
