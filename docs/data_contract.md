# Data Contract

The executable contract is defined in
`src/nz_migration_pipeline/contracts.py`; its machine-readable shape is in
`contracts/canonical_fact.schema.json`.

## Blocking checks

A release must not be published when any of these checks fail:

- A required source or canonical field is missing.
- A month is not valid `YYYY-MM`.
- `year_month` or `source_release_month` is after `snapshot_month`.
- The immutable business key is duplicated inside a snapshot.
- A dimension is blank or `metric_slice` disagrees with its `TOTAL` pattern.
- `estimate` is not a non-negative integer.
- `standard_error` is not a non-negative number.
- `status` is not `Final` or `Provisional`.
- The file digest is not a lowercase SHA-256 value.
- The source is outside the current `Long-term migrant` / `Arrivals` scope.
- The source file is empty, malformed, or has an unexpected header.

Blocking AWS failures are written to the stage-specific quarantine prefix with
the failure ID and error details. Local failures raise a `ContractViolation`.
Neither path writes a completion marker.

## Warning checks

The pipeline records these observations without assigning an uncalibrated
pass/fail threshold:

- Source row count and business-key count.
- Minimum and maximum activity and source-release months.
- Counts by status and metric slice.
- Added, removed, revised, and unchanged facts across adjacent snapshots.
- Maximum absolute estimate revision and revised total-slice count.

Alert thresholds beyond the blocking contract require a historical baseline.
They are deliberately not invented solely to make fixtures pass.

## File-level contract

Each raw release receives a manifest containing:

```json
{
  "release_id": "stats-nz-international-migration-2025-10",
  "snapshot_month": "2025-10",
  "source_uri": "https://www.stats.govt.nz/...csv",
  "source_sha256": "051978fc...a9396abf4",
  "byte_size": 29279381,
  "ingested_at": "<UTC timestamp>",
  "source_key": "raw/release_id=.../source.csv"
}
```

`source_key` is present in the S3 manifest; the local manifest uses the same
fields except that the local path is already deterministic and needs no S3 key.

The digest makes same-name content replacement detectable. Re-ingesting the
same `release_id` and digest is a no-op. The same `release_id` with a different
digest fails and, on AWS, is quarantined for review rather than silently
overwritten.

## Fixture provenance

The committed fixtures are small, unmodified row subsets of public Stats NZ
CSV releases. Their source URLs and full-file SHA-256 digests are recorded in
`tests/fixtures/releases.json`. Stats NZ data is attributed under Creative
Commons Attribution 4.0 International.
