# Canonical Data Model

## Verified source

The model was derived from the official Stats NZ October 2025, November 2025,
and June 2026 CSV releases rather than from the existing Glue catalog schema.

The source is a cube, not three independent breakdown tables:

```text
snapshot
  +-- reporting month
       +-- citizenship (NZ / non-NZ / TOTAL)
       +-- visa (category / TOTAL)
       +-- country of residence (country or region / TOTAL)
            +-- estimate, standard error, status
```

Every combination can be present, including cross-tabs such as `non-NZ` +
`Work` + `India`. Flattening the file into a generic `breakdown_type` table
would discard valid cube relationships. Summing all rows would count the same
population many times.

## Snapshot semantics

Three time concepts must remain separate:

- `snapshot_month`: the release file captured by the pipeline.
- `source_release_month`: the row-level `month_of_release` supplied by Stats NZ.
- `year_month`: the month the estimate describes.

For example, a June 2026 snapshot can contain an older final observation whose
`source_release_month` is 2024-06. The snapshot still belongs to June 2026.

## Metric slices

`metric_slice` is derived from the non-`TOTAL` dimensions.

| Citizenship | Visa | Country | `metric_slice` |
|---|---|---|---|
| TOTAL | TOTAL | TOTAL | `total` |
| value | TOTAL | TOTAL | `citizenship` |
| TOTAL | value | TOTAL | `visa` |
| TOTAL | TOTAL | value | `country_of_residence` |
| value | value | TOTAL | `citizenship_visa` |
| value | TOTAL | value | `citizenship_country_of_residence` |
| TOTAL | value | value | `visa_country_of_residence` |
| value | value | value | `citizenship_visa_country_of_residence` |

This derived field makes safe query intent explicit while retaining every
source dimension.

## Revision comparison

Records are matched across snapshots using the revision key:

```text
year_month, passenger_type, direction,
citizenship, visa, country_of_residence
```

The comparison reports additions, removals, estimate deltas, standard-error
deltas, and status transitions. In the audited total series, October 2025 to
November 2025 changed 16 of 298 common monthly estimates. The October 2024
total was revised from 10,600 to 10,454 arrivals, a delta of -146.

## Storage partitioning

The V2 curated layout will retain every snapshot:

```text
curated/migration_arrivals/
  snapshot_month=2025-10/year_month=2024-10/*.parquet
  snapshot_month=2025-11/year_month=2024-10/*.parquet
```

Published consumers join only snapshot months with a successful commit marker.
Candidate or partial output is therefore invisible. No curated history is
deleted when a new release arrives.
