# Local pipeline

The local runner is a fast Polars/PyArrow harness for the same source contract,
canonical model, revision semantics, and publication invariants. Production
AWS execution uses Glue 5.0 PySpark. The local path is useful for development,
CI, and demonstrating the model without creating cloud resources.

## Install

```bash
python -m pip install -e ".[dev]"
```

## Run a release

```bash
python -m nz_migration_pipeline run-local \
  --source tests/fixtures/source_snapshot_2025_10.csv \
  --release-id fixture-2025-10 \
  --snapshot-month 2025-10 \
  --output-root .local/pipeline
```

`--source` accepts either a local path or an HTTP(S) URL. For official
releases, pass `--expected-sha256` to reject an unexpected or changed download.

## Storage layout

```text
.local/pipeline/
  raw/release_id=<release-id>/
    source.csv
    manifest.json
  curated/migration_arrivals/
    snapshot_month=YYYY-MM/
      _QUALITY.json
      _SUCCESS.json
      _revisions/
        part-00000.parquet
        summary.json
      year_month=YYYY-MM/part-00000.parquet
  metadata/
    releases/<release-id>.json
    runs/<run-id>.json
```

Raw files and completed snapshot partitions are immutable. A repeat using the
same release ID and SHA-256 returns `skipped`. Reusing a release ID or snapshot
month for different content raises a conflict instead of overwriting history.

Parquet data is partitioned first by the file-level `snapshot_month`, then by
the activity-level `year_month`. This keeps every historical source snapshot
reproducible while allowing time-filtered reads.

## Failure behaviour

- Downloads are hashed before storage.
- Raw files and JSON metadata use atomic file replacement.
- A curated snapshot is written to a temporary directory and atomically moved
  into place only after every partition succeeds.
- `_SUCCESS.json` permits the next run to recover if the process stops after
  Parquet commit but before release metadata commit.
- `_QUALITY.json` records the enforced checks, key cardinality, covered months,
  status counts, and metric-slice counts for the accepted snapshot.
- From the second snapshot onward, `_revisions` contains a full outer comparison
  with the preceding successful snapshot. Each fact is labelled `added`,
  `removed`, `revised`, or `unchanged` and includes numeric deltas.
- Contract violations never produce a completion record.

## Verification

```bash
python -m pytest -q
python -m compileall -q src tests Glue/jobs
ruff check src tests Glue/jobs
```
