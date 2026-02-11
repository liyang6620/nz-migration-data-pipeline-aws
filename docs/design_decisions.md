# Engineering Design Decisions

This document explains key technical decisions made in the design of the migration reporting pipeline.

---

## Revision-Aware Data Handling

Stats NZ migration releases may revise historical values.  
To ensure reproducible reporting:

- Data is partitioned by **snapshot_month**
- The pipeline automatically resolves the **latest snapshot**
- Historical reports remain reproducible

---

## Idempotent Pipeline Execution

The pipeline is designed to safely re-run:

- Curated partitions are cleaned before write
- No duplicate records are created
- Deterministic output paths ensure consistent results

---

## Schema Stability

To reduce downstream maintenance:

- Column names and types are standardised
- Schema is enforced in curated layer
- Controlled categorical values used where applicable

---

## Storage Optimisation

- Parquet format used for columnar compression
- Partitioned by `year_month` for efficient query pruning
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

- Schema validation
- Non-null checks
- Row-level validation

Results stored for traceability and debugging.

---

## Serverless Architecture

The pipeline uses fully serverless AWS components:

- Amazon S3 – Storage
- AWS Glue – ETL and schema discovery
- AWS Step Functions – Orchestration
- Amazon Athena – Query layer
- EventBridge – Optional scheduling

This enables:

- No infrastructure management
- Pay-per-use cost model
- Scalable execution
