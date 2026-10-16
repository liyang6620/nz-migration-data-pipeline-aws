# Canonical Migration Fact Data Dictionary

The canonical fact preserves the grain of the Stats NZ
`citizenship-by-visa-by-country-of-last-permanent-residence` release. Each row
is one point in a three-dimensional cube for one reporting month and snapshot.

## Identity and lineage

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `release_id` | string | yes | Stable identifier for the downloaded Stats NZ release. |
| `snapshot_month` | string (`YYYY-MM`) | yes | File-level release captured by this pipeline. This is injected from the immutable raw path and must not be inferred from a row. |
| `source_release_month` | string (`YYYY-MM`) | yes | Stats NZ `month_of_release` value for the individual estimate. It can be older than the file snapshot when a value is final or unchanged. |
| `source_sha256` | string | yes | SHA-256 digest of the exact downloaded source bytes. |
| `ingested_at` | UTC timestamp | yes | Time the pipeline accepted the source file. |
| `schema_version` | string | yes | Version of the canonical contract; currently `1.0.0`. |

## Fact grain

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `year_month` | string (`YYYY-MM`) | yes | Month in which migration activity occurred. |
| `passenger_type` | string | yes | Currently fixed to `Long-term migrant`. |
| `direction` | string | yes | Currently fixed to `Arrivals` because the selected source file contains arrivals only. |
| `citizenship` | string | yes | `NZ`, `non-NZ`, or `TOTAL` in the audited releases. |
| `visa` | string | yes | Visa category or `TOTAL`. |
| `country_of_residence` | string | yes | Country/region of last permanent residence or `TOTAL`. |
| `metric_slice` | enum | yes | Derived from which of the three dimensions are not `TOTAL`; see `docs/data_model.md`. |

The immutable record key is:

```text
snapshot_month
+ year_month
+ passenger_type
+ direction
+ citizenship
+ visa
+ country_of_residence
```

`source_release_month` is lineage, not part of the key. The revision comparison
key is the same key without `snapshot_month`.

## Measures

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `estimate` | integer, >= 0 | yes | Estimated migrant arrivals for the exact cube cell. |
| `standard_error` | double, >= 0 | yes | Standard error supplied by Stats NZ. |
| `status` | enum | yes | `Final` or `Provisional`. |

## Aggregation rule

Never sum the entire fact table. It contains totals, one-dimensional slices,
cross-tabs, and fully detailed cells at the same time.

- Overall monthly KPI: all three dimensions equal `TOTAL`.
- Citizenship breakdown: citizenship is not `TOTAL`; visa and country are `TOTAL`.
- Visa breakdown: visa is not `TOTAL`; citizenship and country are `TOTAL`.
- Country breakdown: country is not `TOTAL`; citizenship and visa are `TOTAL`.

Cross-tab reporting must select exactly one corresponding `metric_slice`.

## Audited source scope

The October 2025 source contained 357,098 rows, three citizenship values,
seven visa values, 249 country/region values, and no duplicate keys at the
canonical source grain. Its observations cover January 2001 through October
2025. The current contract intentionally does not claim departures or net
migration coverage.
