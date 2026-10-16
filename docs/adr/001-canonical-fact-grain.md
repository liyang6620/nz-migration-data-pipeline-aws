# ADR 001: Preserve the Source Cube as the Canonical Fact Grain

- Status: Accepted
- Date: 2026-10-16

## Context

The original repository treated citizenship, visa, and country of residence as
independent breakdowns and exposed views that summed records without fully
constraining the other dimensions. Inspection of the official CSV shows that
the source contains a three-dimensional cube with totals and cross-tabs in the
same file.

The repository also used `month_of_release` as though it were the file
snapshot. It is row-level lineage: old final observations can keep an older
value while appearing in a newer release file.

## Decision

The canonical fact will:

1. Preserve citizenship, visa, and country of residence on every row.
2. Add a file-level `snapshot_month` supplied by the immutable raw path.
3. Rename source `month_of_release` to `source_release_month`.
4. Derive one of eight `metric_slice` values from the `TOTAL` pattern.
5. Use a snapshot-aware immutable key and a snapshot-free revision key.
6. Require reporting queries to select exactly one safe slice.

The current contract is intentionally scoped to long-term migrant arrivals,
which is what the selected source CSV contains.

## Consequences

Positive:

- Overall KPIs cannot accidentally sum totals and detailed cells together.
- Cross-tab analysis remains possible.
- Historical releases can coexist and be compared deterministically.
- Row-level source lineage and file-level snapshot lineage are no longer
  conflated.

Trade-offs:

- Consumers must choose a metric slice explicitly.
- Curated storage retains repeated snapshots and therefore uses more space.
- Departures and net migration require an additional verified source contract;
  they cannot be claimed from this arrivals-only file.

## Rejected alternatives

- Generic `breakdown_type` / `breakdown_value`: loses cross-dimensional facts.
- One table per breakdown: duplicates transformation logic and still omits
  cross-tabs.
- Latest snapshot only: cheaper to reason about but cannot reproduce historical
  reporting or explain revisions.
