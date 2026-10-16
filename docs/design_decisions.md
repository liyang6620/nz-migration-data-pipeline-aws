# Engineering Design Decisions

This document explains key technical decisions made in the design of the migration reporting pipeline.

---

## Revision-Aware Data Handling

Stats NZ migration releases may revise historical values.  
To ensure reproducible reporting:

- File-level `snapshot_month` is separate from the row-level
  `month_of_release` lineage value.
- Curated data is partitioned by `snapshot_month` and `year_month`.
- Published consumers resolve only snapshots with a successful commit marker.
- Historical snapshots are immutable and are never deleted by a new run.
- Revision reports compare stable fact keys across adjacent snapshots.

---

## Idempotent Pipeline Execution

The pipeline is designed to safely re-run:

- The source SHA-256 digest detects repeated or replaced releases.
- S3 bucket, object key, and version ID form the AWS idempotency key.
- Successful and active deliveries are no-ops; failed or quarantined versions
  can be replayed without deleting their registry record.
- Deterministic snapshot paths prevent duplicate records.
- A conflicting digest is quarantined instead of overwriting history.

---

## Schema Stability

To reduce downstream maintenance:

- Column names and types are standardised
- Schema is enforced in curated layer
- The executable contract and JSON Schema are versioned in the repository
- Metric slices are derived deterministically from source cube dimensions

---

## Storage Optimisation

- Parquet format used for columnar compression
- Partitioned by `snapshot_month` and `year_month` for reproducibility and
  query pruning
- Reduces Athena scan cost

---

## Semantic Reporting Layer

Athena views define governed metrics:

- Monthly arrivals KPI
- Country and visa breakdowns
- Reusable fact dataset

Ensures consistent reporting definitions across dashboards and analysts.

---

## Data Quality Monitoring

Each run performs:

- Exact source-header and schema validation
- Null, numeric, domain, and temporal checks
- Canonical business-key uniqueness checks
- Metric-slice classification and total-slice presence checks
- Full revision comparison with the preceding successful snapshot

Quality evidence and revision summaries are committed atomically with each
snapshot. Rejected AWS transformations write a structured quarantine record.

---

## Event-driven AWS architecture

The runtime uses AWS-managed, request-driven components:

- Amazon S3 for landing, immutable raw, staged, curated, quality, revision,
  quarantine, commit, and audit objects
- EventBridge, SQS FIFO, and EventBridge Pipes for filtered durable delivery
- Step Functions Standard for orchestration and publication state
- DynamoDB for idempotency, run state, and a dataset publication lock
- AWS Glue 5.0 PySpark and Glue Data Quality for distributed ETL
- Glue Data Catalog and Lake Formation for schema and governed access
- Athena for post-write validation and stable Gold views
- CloudWatch, SNS, and AWS Budgets for operational and cost visibility

This enables:

- no source polling or always-on compute;
- pay-per-use processing only after a contracted upload;
- a US$3 budget alert plus bounded workers, runtime, concurrency, and scans.
