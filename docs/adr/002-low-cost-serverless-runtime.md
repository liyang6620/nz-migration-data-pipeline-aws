# ADR 002: Use Lambda containers instead of Glue Spark

- Status: Accepted
- Date: 2026-10-16

## Context

The source is one monthly CSV of roughly 350,000 rows. The legacy Glue job
allocated ten G.1X workers and a recent run consumed 0.432222 DPU-hours. That
capacity and startup model are disproportionate to this workload and conflict
with the project's US$3 monthly ceiling.

The transformation needs reliable columnar types, Parquet output, and efficient
full-snapshot comparison. Its Python dependencies are larger than a comfortable
Lambda ZIP package.

## Decision

Run two image-based Lambda functions from one immutable ECR image:

1. Ingest downloads, hashes, and commits the raw release manifest.
2. Transform validates with Polars, writes Parquet with PyArrow, and publishes
   quality and revision artifacts.

Step Functions coordinates the stages. S3 is the system of record, Glue is used
only as the Data Catalog, and Athena is the query layer. Each function has
reserved concurrency of one, and no VPC or NAT Gateway is created.

## Consequences

- There is no idle compute cost and expected monthly invocation cost is tiny.
- A container image avoids Lambda layer and ZIP size constraints.
- ECR adds a small storage charge, bounded by retaining only five images.
- The 15-minute Lambda ceiling limits future source growth. A measured breach,
  not hypothetical scale, would trigger reconsideration of Fargate or Glue.
- Ingest requires public internet access, so the functions remain outside a VPC.
