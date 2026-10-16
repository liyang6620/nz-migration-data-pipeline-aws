# ADR 004: Build an event-driven AWS data product

- Status: Accepted and frozen for implementation
- Date: 2026-10-17
- Supersedes: ADR 002

## Context

This system is designed as a company-operated data pipeline for analysts, BI
tools, and downstream consumers. The GitHub repository is an implementation
artifact, not the product control plane. Runtime ingestion, orchestration,
processing, quality gating, publication, governance, querying, and operational
evidence must remain inside AWS.

The source is low-volume and file-based. Continuous polling and always-on
compute are unnecessary. A completed upload is the product's ingestion event.
The deployment must retain the US$3 monthly demo ceiling without weakening the
correctness, replayability, security, or auditability of the design.

## Decision

Use the following event-driven AWS runtime:

1. A source CSV is uploaded to a contract-defined S3 landing key.
2. S3 Object Created events are filtered by EventBridge.
3. SQS FIFO buffers ordered work; a dead-letter queue retains exhausted
   failures.
4. EventBridge Pipes starts a Step Functions Standard execution for each
   accepted object.
5. DynamoDB stores the release registry, run state, idempotency key, and
   dataset-level processing lock.
6. Step Functions coordinates validation, Glue 5.0 Spark ETL, data quality,
   publication, Athena validation, state updates, retries, and failure paths.
7. S3 stores immutable raw inputs, staged output, curated Parquet, quality
   evidence, revision evidence, query results, and run audit records.
8. Glue Data Catalog provides explicit schemas and partition projection. Glue
   Data Quality rules gate publication.
9. Lake Formation separates pipeline, analyst, and BI access.
10. Pre-created Athena Gold views expose stable business semantics and only
    consume successfully committed snapshots.
11. CloudWatch records run-scoped logs and metrics. EventBridge and SNS emit
    failure-only notifications. No service continuously polls the source.
12. Terraform defines all AWS resources and cost controls.

The initial Gold views are:

- `gold.vw_latest_monthly_arrivals`
- `gold.vw_total_arrivals`
- `gold.vw_arrivals_by_citizenship`
- `gold.vw_arrivals_by_visa`
- `gold.vw_revision_summary`
- `gold.vw_release_history`
- `gold.vw_pipeline_quality`

The processing lifecycle is:

```text
RECEIVED -> VALIDATING -> TRANSFORMING -> QUALITY_CHECK
         -> PUBLISHING -> VALIDATING_OUTPUT -> SUCCEEDED

Any active state -> FAILED or QUARANTINED
```

S3 and EventBridge provide at-least-once delivery. Effective exactly-once
processing is achieved with a stable object-version idempotency key, DynamoDB
conditional writes, immutable releases, and commit-marker publication. Failed
or partial snapshots are never visible through the Gold views.

## Data decisions

Business filtering, quality thresholds, anomaly limits, dimensions retained in
Gold views, and aggregation rules will be decided from evidence rather than
assumed during architecture work. Implementation begins with profiling the
official full releases for distributions, nulls, duplicates, cardinality,
revision behaviour, and valid source-domain values.

The following decisions are already fixed because they follow from verified
source semantics:

- The canonical grain includes snapshot month, activity month, passenger type,
  direction, citizenship, visa, and country of residence.
- `TOTAL` rows represent aggregation levels within a three-dimensional cube and
  must not be summed together.
- Headline arrivals use only the triple-`TOTAL` metric slice.
- Historical source revisions are first-class output, not overwritten data.

Any additional filter or threshold must be documented with its profiling
evidence and consumer impact before it becomes a production rule.

## Product standards

Implementation is not complete until it provides:

- immutable raw retention and SHA-256 provenance;
- deterministic schemas and an explicit compatibility policy;
- replay and historical backfill without code edits;
- idempotent handling of duplicate and out-of-order events;
- quarantine for invalid inputs;
- staged writes and commit-marker publication;
- data quality evidence and release-level audit records;
- least-privilege IAM and no root or long-lived access keys;
- isolated development and production configuration;
- bounded concurrency, timeouts, retries, DLQ recovery, and runbooks;
- post-publication Athena smoke tests;
- consumer access restricted to approved Gold interfaces;
- cost tags, lifecycle policies, Athena scan limits, and a US$3 demo budget.

## Cost boundary

There is no schedule, source polling, or always-on compute. Costs are incurred
only after an accepted upload. Glue Spark is the primary variable cost; worker
count, timeout, and concurrency are capped. S3 lifecycle rules, an Athena
one-gigabyte per-query cutoff, short log retention, and budget notifications
bound the remaining services.

The deployed portfolio environment is a cost-scaled implementation of a
company-oriented architecture. It must not claim multi-account enterprise
governance, cross-region disaster recovery, or 24/7 commercial support that is
not actually implemented.

## Consequences

- The runtime is independent of GitHub Actions and remains entirely in AWS.
- Uploads are durable, buffered, replayable, and observable without continuous
  monitoring.
- Glue/PySpark demonstrates distributed ETL while Step Functions provides a
  durable product control plane.
- Additional services increase infrastructure code and integration testing,
  but every component owns a concrete reliability or governance concern.
- The Lambda container and ECR design in ADR 002 is retired. Existing resources
  are changed only through a reviewed Terraform plan in a later implementation
  session.
