# Engineering Design Decisions

This document explains key technical decisions made in the design of the migration reporting pipeline.

---

## Revision-Aware Data Handling

Stats NZ migration releases may revise historical values.  
To ensure reproducible reporting:

- File-level `snapshot_month` is separate from the row-level
  `month_of_release` lineage value.
- Curated data is partitioned by `snapshot_month` and `year_month`.
- Published consumers resolve the latest accepted snapshot through a manifest.
- Historical snapshots are immutable and are never deleted by a new run.
- Revision reports compare stable fact keys across adjacent snapshots.

---

## Idempotent Pipeline Execution

The pipeline is designed to safely re-run:

- The source SHA-256 digest detects repeated or replaced releases.
- A matching release ID and digest is a no-op.
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

## Serverless Architecture

The V2 pipeline uses fully serverless AWS components:

- Amazon S3 – Storage
- AWS Lambda – Polars/PyArrow ingestion and transformation
- AWS Glue Data Catalog – Athena schema with partition projection
- AWS Step Functions – Orchestration
- Amazon Athena – Query layer
- EventBridge – Optional scheduling

This enables:

- No infrastructure management
- Pay-per-use cost model
- A US$3 project budget and bounded concurrency/query scans
