# NZ Migration Reporting Pipeline (AWS)

## Production-style Serverless Data Engineering Project

---

## Project Overview

This project implements a serverless data pipeline designed to support recurring monthly reporting on New Zealand long-term migration trends.

The pipeline ingests official migration release data from **Statistics New Zealand (Stats NZ)**, stabilises revised historical records, and produces a consistent, analytics-ready dataset used by an internal Analytics & Reporting team.

The primary goal is to ensure that reports generated at different points in time remain **reproducible**, even when upstream source data is revised.

---

## Primary User and Usage

**Primary user:** Internal Analytics & Reporting team  
**Usage frequency:** Monthly reporting cycle  

The Analytics team uses the outputs of this pipeline to:

- Generate a monthly KPI pack (arrivals, departures, net migration)
- Populate dashboards for trend monitoring
- Perform consistent month-over-month comparisons
- Reproduce historical reports when questions arise about past results

This pipeline is not intended for policy analysis or forecasting. Its sole purpose is to provide **reliable and repeatable reporting data**.

---

## Problem Statement

Without an engineered ingestion layer, migration reporting built directly on Stats NZ release files suffers from:

1. **Historical revisions** that change previously reported values  
2. **Schema inconsistencies** that increase maintenance effort  
3. **Lack of reproducibility** for past reporting cycles  

This project solves these issues by introducing a controlled ingestion and curation process that stabilises the data before it reaches analysts.

---

## Data Source

Official public releases published by **Statistics New Zealand (Stats NZ)**:

https://www.stats.govt.nz/information-releases/international-migration-october-2025/

The dataset is used as an external input only. All transformations and derived outputs are independent and do not represent official Stats NZ publications.

---

## Key Features

- Automated ingestion and transformation of Stats NZ migration releases
- Revision-aware handling strategy (supports reproducible reporting)
- Idempotent execution (safe re-runs without duplication)
- Partitioned Parquet dataset optimised for analytics queries
- Standardised reporting views (semantic layer) in Amazon Athena
- Data quality checks and run-level metadata for traceability
- Fully serverless architecture with cost-efficient design

---

## Pipeline Outputs

### 1) Curated Migration Fact Dataset (S3)

- Stored in Amazon S3  
- Format: Parquet  
- Partitioned by `year_month`  
- Schema standardised across runs  

This dataset serves as the **single source of truth** for reporting.

**Example partition path:**
- `s3://nz-migration-data-yangli/curated/migration_arrivals_facts/Arrivals/Long-term/year_month=2001-06/`

---

### 2) Reporting Views (Amazon Athena)

A small, fixed set of Athena views defines the reporting logic used by analysts. These views act as the **semantic layer** between curated data and dashboards / KPI packs.

| View | Purpose | Typical Consumer |
|------|---------|------------------|
| `vw_arrivals_facts` | Cleaned fact-level arrivals dataset used as the base for downstream reporting | Analysts / modelling layer |
| `vw_arrivals_monthly_kpi` | Monthly KPI time series for long-term arrivals (report-ready aggregation) | KPI pack / dashboards |
| `vw_arrivals_by_visa_monthly` | Monthly arrivals grouped by visa category for segmentation reporting | Breakdown reporting |
| `vw_arrivals_by_country_monthly` | Monthly arrivals grouped by country/citizenship for geo reporting | Trend monitoring |

These views standardise definitions (filters, grouping logic, consistent field naming) so reporting remains reproducible across cycles.

---

### 3) Run Metadata & Data Quality Summary

Each pipeline execution records operational metadata for traceability:

- Snapshot / release identifier
- Processing timestamp
- Validation results (basic DQ rules)

This supports investigation and reproducibility when data questions arise.

---

## Engineering Design

### Idempotent Execution

The pipeline is designed to be safely re-run:

- Deterministic output paths
- Controlled overwrite / cleanup strategy before write
- No duplicate record creation across runs

---

### Schema Stability

To minimise downstream breakage:

- Fixed column names and data types
- Controlled categorical values where applicable
- Schema validation prior to writing curated outputs

---

### Cost Optimisation

- Parquet format reduces Athena scan cost
- Time-based partitioning enables partition pruning
- Fully serverless services avoid idle infrastructure cost

---

## Architecture

Serverless AWS stack:

- **Amazon S3** – raw data, curated datasets, metadata / quality logs  
- **AWS Glue** – ETL transformation and schema enforcement  
- **AWS Step Functions** – orchestration (crawler → snapshot resolution → clean → ETL → DQ)  
- **Amazon Athena** – reporting views and quality queries  
- **Amazon EventBridge** – optional scheduling trigger  

ORDER BY year_month DESC
LIMIT 24;


