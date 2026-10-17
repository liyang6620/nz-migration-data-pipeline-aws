# Five-minute interview demo

This path demonstrates data engineering and AWS capability without spending
interview time on repository navigation.

## 0:00 - Business and data problem

Stats NZ republishes a large statistical cube and can revise historical facts.
The product must preserve every source version, prevent dimensional
double-counting, identify revisions, and expose only completely validated
snapshots to analysts.

Show the canonical grain and explain why `TOTAL` is an aggregation level rather
than a category. This is the key modelling decision.

## 0:45 - AWS data flow

Walk left to right through the README architecture:

1. A versioned S3 upload emits an event.
2. EventBridge and SQS FIFO provide filtered, durable delivery.
3. EventBridge Pipes starts Step Functions without Lambda.
4. DynamoDB enforces idempotency and a publication lock.
5. Glue 5.0 performs schema enforcement, PySpark transformation, quality
   checks, Parquet publication, and revision comparison.
6. Athena validates staged output before the workflow writes a commit marker.
7. Glue Catalog and Lake Formation expose only committed Gold views.

Emphasise that GitHub Actions validates repository code only. It is not part of
the production data path.

## 2:00 - Reliability controls

Use one sentence per control:

- S3 version ID is part of the run identity, so duplicate delivery is safe.
- Raw and audit evidence are immutable and versioned.
- Failed quality gates produce quarantine evidence, never a commit marker.
- A staging candidate becomes visible only after Athena validation.
- A failed or quarantined version can be replayed without deleting history.
- SQS DLQ, CloudWatch, and SNS cover delivery and execution failures.

For a failure question, describe replaying the original versioned S3 event
after fixing the cause. Do not propose manually copying files into curated.

## 3:10 - Live evidence

Show the production validation image and then the deployment evidence table:

- two complete official snapshots committed;
- 358,233 facts in the latest snapshot;
- both quality records passed;
- 24,279 historical facts revised between releases;
- latest Glue run completed in 196 seconds;
- Terraform reported zero drift after deployment.

The important outcome is not only that ETL ran. Consumers see a stable,
revision-aware contract and cannot query an incomplete release.

## 4:10 - Cost and engineering trade-offs

Explain the deliberate constraints:

- upload-triggered rather than real-time because the source is monthly;
- Glue rather than always-on Spark infrastructure;
- Athena Parquet views rather than Redshift for low query volume;
- no NAT Gateway, MWAA, EC2, ECS, QuickSight, or polling schedule;
- two G.1X workers, one concurrent run, 15-minute timeout, 1 GB Athena cutoff,
  lifecycle expiry, 14-day logs, and a US$3 budget alert.

Close with the trade-off: this is a production-shaped single-account data
product, not a claim of multi-region or 24/7 enterprise operations.

## Likely follow-up questions

**Why SQS FIFO if S3 events can be duplicated?**

FIFO improves ordered, durable delivery, while true idempotency still comes
from the S3 object version recorded in DynamoDB.

**Why a commit marker?**

S3 rename is copy-and-delete, not an atomic directory transaction. The commit
record is the publication authority consumed by Gold views.

**How do you handle schema evolution?**

The source header, canonical JSON Schema, compatibility policy, and consumer
views are versioned. Breaking changes require a new contract rather than silent
column drift.

**What would change at company scale?**

Use dedicated deployment roles, remote locked Terraform state, separate
accounts and environments, central observability, formal data ownership, and
consumer SLAs. None are falsely claimed by this portfolio deployment.

