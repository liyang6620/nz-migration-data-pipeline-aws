# NZ Migration Data Pipeline (AWS)

## Overview

This repository contains an AWS-based data pipeline for ingesting and operationalising official New Zealand international migration data published by Statistics New Zealand.

The pipeline is designed to convert monthly CSV releases into analytics-ready datasets that can be reliably queried and reused by downstream analysis and reporting workflows.

---

## Data Source & Licensing

Data is sourced from Statistics New Zealand (Stats NZ).

Source release:
https://www.stats.govt.nz/information-releases/international-migration-october-2025/

This project uses the data for internal processing and analytical purposes only.  
All transformations and interpretations are independent and do not represent official Stats NZ publications.

---

## What This Pipeline Does

At a high level, the pipeline performs the following steps:

- Ingests monthly migration release data into an S3-based raw data zone
- Cleans and standardises the source data
- Converts data into partitioned Parquet format for efficient querying
- Applies data quality checks and records quality metrics per run
- Stores curated datasets for downstream analytical use
- Supports optional scheduled execution aligned with data releases

---

## Architecture

The pipeline uses a serverless AWS architecture focused on simplicity, reliability, and cost control.

Core components include:

- Amazon S3 for raw, curated, and quality datasets
- AWS Lambda for data ingestion and transformation
- Amazon Athena for analytical querying
- Amazon EventBridge for optional scheduling
- Amazon CloudWatch for logging and monitoring

An architecture diagram will be added as the implementation progresses.

---

## Data Quality and Validation

Data quality checks are applied during each pipeline run to ensure consistency and reliability of downstream datasets.

These checks include schema validation, basic value constraints, and tracking of missing or invalid records.  
Each execution produces a run-level quality report, with selected metrics appended to a historical quality log for trend monitoring.

Detailed rules and validation logic are documented under `quality/`.

---

## Analytics and Query Layer

Curated datasets are stored in partitioned Parquet format and exposed via Athena tables and views.

This allows downstream users to perform common analytical queries such as:
- Monthly arrivals and departures
- Net migration trends over time
- Breakdown by citizenship, visa type, and country of last permanent residence

Representative query outputs will be included once the pipeline is executed.

---

## Automation and Scheduling

The pipeline supports scheduled execution using Amazon EventBridge.

For cost-control and demonstration purposes, scheduling is disabled by default.  
In a production environment, the pipeline would typically run on a monthly cadence aligned with official data releases.

---

## Operational Considerations

The pipeline is designed with operational concerns in mind, including:

- Idempotent execution to support safe re-runs
- Structured logging for traceability
- Basic monitoring and failure detection
- Clear separation of raw and curated data

Operational procedures and recovery steps will be documented under `docs/`.

---

## Cost Control

The architecture avoids always-on resources and relies on serverless services to minimise cost.

Partitioned Parquet storage is used to reduce query scan volume, and all resources can be fully removed after use to avoid ongoing charges.

---

## Reproducibility and Cleanup

Deployment and cleanup instructions will be documented to ensure the environment can be reproduced and fully torn down when no longer required.
