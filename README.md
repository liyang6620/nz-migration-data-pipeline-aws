# NZ Migration Data Product on AWS

[![CI](https://github.com/liyang6620/nz-migration-data-pipeline-aws/actions/workflows/ci.yml/badge.svg)](https://github.com/liyang6620/nz-migration-data-pipeline-aws/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg)](pyproject.toml)
[![AWS Glue 5.0](https://img.shields.io/badge/AWS-Glue%205.0-FF9900.svg)](Glue/jobs/process_migration.py)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC.svg)](infrastructure/terraform)
[![License: MIT](https://img.shields.io/badge/Code-MIT-yellow.svg)](LICENSE)

An event-driven AWS data product for official Statistics New Zealand long-term
migration arrivals. A contracted S3 upload starts a durable pipeline that
preserves the source, validates and transforms the complete statistical cube,
publishes revision-aware Parquet, and exposes only committed snapshots through
governed Athena Gold views.

This is designed as a small company-operated pipeline, not as a notebook or a
GitHub Actions demo. Runtime ingestion, buffering, orchestration, processing,
quality gates, publication, governance, querying, monitoring, and replay all
remain inside AWS.

## Architecture

~~~mermaid
flowchart LR
    U[CSV upload] --> L[S3 landing]
    L --> EB[EventBridge]
    EB --> Q[SQS FIFO]
    Q -. exhausted delivery .-> DLQ[Dead-letter queue]
    Q --> P[EventBridge Pipes]
    P --> SF[Step Functions Standard]
    SF <--> DDB[(DynamoDB run registry<br/>idempotency + dataset lock)]
    SF --> G[AWS Glue 5.0<br/>PySpark ETL + Data Quality]
    G --> RAW[(immutable raw)]
    G --> STG[(staging)]
    G --> CUR[(curated Parquet)]
    G --> REV[(revision evidence)]
    G --> DQ[(quality evidence)]
    SF --> ATH[Athena validation]
    ATH --> COMMIT[(commit marker)]
    COMMIT --> CAT[Glue Catalog]
    CUR --> CAT
    REV --> CAT
    DQ --> CAT
    CAT --> LF[Lake Formation]
    LF --> GOLD[7 Athena Gold views]
    GOLD --> C[analysts / BI / downstream users]
    SF -. failures .-> QUAR[quarantine + audit]
    SF -. telemetry .-> CW[CloudWatch + SNS]
    BUD[AWS Budget: US$3] -. alerts .-> SNS
~~~

There is no polling schedule and no always-on compute. The pipeline runs only
when a file is uploaded to:

~~~text
landing/dataset=migration/
  snapshot_month=YYYY-MM/
  release_id=<safe-release-id>/
  source.csv
~~~

## Deployed validation

![Sanitised production validation summary](docs/assets/production-validation.png)

The live `ap-southeast-2` deployment has processed and committed two complete
official releases. Both pipeline-quality records passed, the latest Gold view
contains **358,233** November facts, the latest Glue run completed in **196
seconds**, and a post-deployment Terraform plan reported **zero drift**.

The image is a sanitised summary of reproducible AWS results, not a Console
screenshot. Exact checks, operational identifiers, queries, and the evidence
boundary are recorded in [AWS deployment evidence](docs/deployment_evidence.md).
For a concise walkthrough, use the [five-minute interview demo](docs/interview_demo.md).

## Engineering guarantees

- S3 version ID is part of the idempotency key, so duplicate delivery is safe.
- DynamoDB records every run and serialises dataset publication with a lock.
- Failed and quarantined runs can be replayed; successful runs are not repeated.
- Raw files are immutable and tied to a SHA-256 provenance manifest.
- Glue uses an explicit source schema and rejects nulls, invalid domains,
  negative measures, future months, and duplicate business keys.
- Glue Data Quality provides independent, persisted rule outcomes.
- Staging output is hidden until Athena validation succeeds and Step Functions
  writes the release commit marker.
- Interrupted uncommitted output can be replaced safely on retry.
- Invalid data is retained in quarantine; delivery failures remain in a DLQ.
- Consumers query stable Gold views, never incomplete snapshots.
- Infrastructure, IAM, lifecycle, monitoring, and cost controls are Terraform.

The run lifecycle is:

~~~text
RECEIVED -> TRANSFORMING -> QUALITY_CHECK -> SUCCEEDED
                  |                |
                  +-> FAILED / QUARANTINED
~~~

## Data model

The source is a three-dimensional statistical cube:

~~~text
citizenship x visa x country_of_residence
~~~

TOTAL is an aggregation level, not an ordinary category. Summing the full file
would double-count arrivals, so the pipeline derives eight explicit
metric_slice values. Headline KPIs use only the triple-TOTAL slice.

The canonical key is:

~~~text
snapshot_month + year_month + passenger_type + direction
+ citizenship + visa + country_of_residence
~~~

The revision key removes snapshot_month, allowing the same fact to be compared
across official releases. Zero estimates and provisional rows are retained
because both are valid source facts.

## Consumer interface

The **nz_migration_v2_gold** database contains:

| View | Contract |
|---|---|
| **vw_latest_monthly_arrivals** | Complete latest committed canonical snapshot |
| **vw_total_arrivals** | One headline arrivals fact per activity month |
| **vw_arrivals_by_citizenship** | Citizenship series without cube double-counting |
| **vw_arrivals_by_visa** | Visa series without cube double-counting |
| **vw_revision_summary** | Added, removed, revised, and unchanged fact counts |
| **vw_release_history** | Successful releases and row-level coverage |
| **vw_pipeline_quality** | Quality status and evidence for committed releases |

Example:

~~~sql
SELECT year_month, arrivals, standard_error, status
FROM nz_migration_v2_gold.vw_total_arrivals
ORDER BY year_month;
~~~

## Verified source evidence

The implementation was profiled against two complete official releases:

| Snapshot | Source rows | Activity months | Nulls | Duplicate keys |
|---|---:|---:|---:|---:|
| 2025-10 | 357,098 | 298 | 0 | 0 |
| 2025-11 | 358,233 | 299 | 0 | 0 |

The November comparison produced 359,312 revision keys:

| Change | Facts |
|---|---:|
| Added | 2,214 |
| Removed | 1,079 |
| Revised | 24,279 |
| Unchanged | 331,740 |

Sixteen headline estimates changed. October 2024 arrivals, for example, moved
from **10,600** to **10,454** (-146). These results come from the pipeline's
revision output, not hard-coded report logic. See
[the empirical profile](docs/data_profile.md).

## Local verification

Python 3.11 or newer is required.

~~~bash
python -m pip install -e ".[dev]"
python -m nz_migration_pipeline run-local \
  --source tests/fixtures/source_snapshot_2025_10.csv \
  --release-id fixture-2025-10 \
  --snapshot-month 2025-10 \
  --output-root .local/pipeline
pytest -q
ruff check src tests Glue/jobs
terraform -chdir=infrastructure/terraform fmt -check -recursive
terraform -chdir=infrastructure/terraform validate
~~~

The local Polars/PyArrow path is a fast contract and revision test harness. AWS
production execution uses Glue 5.0 PySpark.

GitHub Actions runs these repository checks on pushes and pull requests. It
does not ingest, orchestrate, transform, or publish production data; the runtime
path remains entirely inside AWS.

## AWS deployment

Terraform must be run against the intended personal account and region. The
safe sequence is:

1. Verify the caller identity.
2. Run terraform plan -out=tfplan.
3. Review every create, update, and delete plus the cost boundary.
4. Apply only the reviewed plan.
5. Upload the oldest backfill release first.
6. Verify the Step Functions run, commit marker, Gold views, and alarms.

Deployment commands and rollback notes are in
[the Terraform guide](infrastructure/terraform/README.md). Operations, replay,
DLQ handling, and stale-lock recovery are in
[the runbook](docs/operations_runbook.md).

## Cost boundary

The portfolio environment targets two release runs per month and a
**US$3/month alert threshold**. The budget is an alert, not a hard spending cap.

| Service | Cost behaviour |
|---|---|
| Glue 5.0 | 2 G.1X workers, one concurrent run, 15-minute hard timeout |
| S3 | Tens of MB per release; staging and landing have lifecycle expiry |
| Step Functions | One Standard execution per accepted object |
| SQS / EventBridge / Pipes / DynamoDB | Low-volume, request-based usage |
| Athena | Parquet plus a 1 GB per-query workgroup cutoff |
| Catalog / Lake Formation | Metadata and permissions at this scale |
| CloudWatch / SNS | 14-day logs and failure-focused alerts |

At typical 3-8 minute Glue runtimes, two monthly releases should remain well
below US$1. Even two full 15-minute runs are expected to remain below US$0.50
for Glue compute at common regional pricing; AWS prices and unrelated account
usage must still be checked. No NAT Gateway, EC2, ECS, Redshift, QuickSight, or
MWAA resource is created.

## Repository map

| Path | Purpose |
|---|---|
| **Glue/jobs/** | Production PySpark ETL and publication logic |
| **Glue/rulesets/** | Glue Data Quality contract |
| **infrastructure/terraform/** | Complete AWS runtime and IAM |
| **src/nz_migration_pipeline/** | Local contract/revision test harness |
| **contracts/** | Machine-readable canonical schema |
| **tests/** | Data, runtime, infrastructure, and asset contracts |
| **docs/adr/** | Architecture decisions and superseded alternatives |
| **docs/** | Data model, deployment evidence, demo guide, policies, and runbook |

## Scope and attribution

The verified source supports **long-term migrant arrivals only**. This project
does not claim departures, net migration, forecasting, multi-account
governance, cross-region disaster recovery, or 24/7 commercial support.

Source data is published by [Stats NZ](https://www.stats.govt.nz/) under the
Creative Commons Attribution 4.0 International licence. Repository code is
licensed under [MIT](LICENSE). Outputs are independent transformations and are
not official Stats NZ publications.
