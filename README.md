# NZ Migration Reporting Pipeline (AWS)

## Project Overview

This project implements a data pipeline used by an internal **Analytics and Reporting team** to support recurring monthly reporting on New Zealand long-term migration trends.

The Analytics team produces standard reports and dashboards tracking **monthly arrivals, departures, and net migration**. The source data published by Statistics New Zealand (Stats NZ) is released as monthly CSV files and may revise historical values over time. As a result, direct analysis of raw release files leads to inconsistent results and non-reproducible reports.

This pipeline provides the Analytics team with a **stable, analytics-ready dataset and a small set of standard query views** that act as the single source of truth for migration reporting. The focus of the project is to ensure that the same report generated at different points in time produces consistent results, even when upstream data is revised.

---

## Primary User and Usage

**Primary user:** Internal Analytics and Reporting team  
**Usage frequency:** Monthly reporting cycle  

The Analytics team uses the outputs of this pipeline to:

- Generate a fixed monthly KPI pack covering arrivals, departures, and net migration
- Populate dashboards used for internal trend monitoring
- Perform consistent month-over-month comparisons without reprocessing raw CSV files
- Reproduce historical reports when questions arise about prior results

The pipeline is not intended for policy analysis or forecasting. Its sole purpose is to provide **reliable and repeatable reporting data**.

---

## Problem Statement

Without an engineered ingestion layer, migration reports built directly on Stats NZ release files suffer from three operational issues:

1. **Historical revisions** cause previously reported numbers to change unexpectedly  
2. **Schema inconsistencies** across releases increase downstream maintenance effort  
3. **Lack of version control** makes it difficult to reproduce past reports  

This project solves these problems by introducing a controlled ingestion and curation process that stabilises the data before it reaches analysts.

---

## Data Source

Data is sourced from official releases published by **Statistics New Zealand (Stats NZ)**.

Example release page:  
https://www.stats.govt.nz/information-releases/international-migration-october-2025/

The dataset is used as a publicly available external input. All transformations and derived outputs are independent and do not represent official Stats NZ publications.

---

## Pipeline Outputs

The pipeline produces three core outputs consumed by the Analytics team.

### 1) Curated Migration Fact Dataset

- Stored in Amazon S3
- Format: Parquet
- Partitioned by `year_month`
- Schema standardised and enforced across runs

This dataset serves as the base fact table for all reporting queries.

---

### 2) Reporting Views (Athena)

A small, fixed set of Athena views defines the reporting logic used by analysts, including:

- Monthly long-term arrivals
- Monthly long-term departures
- Monthly net migration (arrivals minus departures)
- Optional breakdowns by visa type and citizenship

These views represent the **official internal reporting definitions** and are reused across reports and dashboards.

---

### 3) Run Metadata and Data Quality Summary

Each pipeline execution records:

- Source release identifier
- Processing timestamp
- Raw vs curated row counts
- Basic validation results

This metadata supports traceability and helps diagnose discrepancies in reporting outputs.

---

## Key Engineering Decisions

### Handling Revised Source Data

Stats NZ migration data may revise historical values in later releases. To preserve reporting consistency, the pipeline supports an explicit revision-handling strategy:

- **Final-only mode (default):** Reporting views use records marked as `Final` to ensure month-over-month comparability.
- **Latest-release mode (optional):** Keeps the most recent record per month for near-real-time monitoring.

The selected mode is documented and reproducible.

---

### Idempotent Execution

The pipeline is designed to be safely re-run:

- Deterministic output paths
- Controlled overwrite strategy
- No duplicate record creation across runs

---

### Schema Stability

To minimise downstream breakage, the pipeline enforces:

- Fixed column names and data types
- Controlled categorical values where applicable
- Schema validation prior to writing curated outputs

---

### Cost Control

- Parquet format to reduce query scan volume
- Time-based partitioning for efficient filtering
- Serverless execution to avoid idle compute cost

---

## Architecture

The pipeline uses a **serverless AWS architecture**:

- **Amazon S3** – raw data, curated datasets, run metadata  
- **AWS Lambda** – ingestion and transformation logic  
- **Amazon Athena** – analytical querying and reporting views  
- **Amazon EventBridge** – optional monthly scheduling  
- **Amazon CloudWatch** – logging and monitoring  

An architecture diagram will be added as implementation progresses.

---

## Data Quality and Validation

Each run performs basic data quality checks, including:

- Schema validation
- Non-null checks on key fields
- Row count comparison between raw and curated layers

Quality metrics are written per run and appended to a historical log for monitoring.

---

## Automation and Scheduling

The pipeline supports monthly execution aligned with official data releases.

For cost control and demonstration purposes, scheduling is disabled by default and runs are triggered manually.

---

## Reproducibility and Cleanup

Deployment and teardown instructions will be provided to allow the environment to be recreated and fully removed when no longer required.

