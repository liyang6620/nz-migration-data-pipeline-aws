# Empirical source profile

This profile records the evidence used to choose pipeline contracts and Gold
semantics. It was produced from complete official Stats NZ CSV releases, not
from the small test fixtures.

## Release comparison

| Measure | 2025-10 | 2025-11 |
|---|---:|---:|
| Rows | 357,098 | 358,233 |
| Activity range | 2001-01 to 2025-10 | 2001-01 to 2025-11 |
| Distinct activity months | 298 | 299 |
| Null values | 0 | 0 |
| Duplicate canonical keys | 0 | 0 |
| Final rows | 331,740 | 333,122 |
| Provisional rows | 25,358 | 25,111 |
| Triple-TOTAL headline rows | 298 | 299 |
| Citizenship values | 3 | 3 |
| Visa values | 7 | 7 |
| Residence values | 249 | 250 |

Observed source domains:

- passenger_type: Long-term migrant
- direction: Arrivals
- citizenship: NZ, non-NZ, TOTAL
- visa: NZ and Australian citizens, Other, Resident, Student, TOTAL, Visitor,
  Work
- status: Final, Provisional

Final data ends at 2024-07 in the observed releases. Provisional data begins at
2024-08.

## Decisions supported by the evidence

- Do not discard zero estimates: zero is a valid measure, not missing data.
- Do not discard Provisional rows: they are the only current estimates for the
  newest activity months.
- Do not aggregate the complete source file. TOTAL rows already encode the
  source cube's aggregation levels.
- Retain all eight metric slices. They support headline, one-dimensional,
  two-dimensional, and full-grain analysis without double-counting.
- Expose headline trends only from metric_slice = total.
- Treat historical revisions as data. Between October and November, 24,279
  facts changed and 16 headline estimates changed.
- Reject unexpected new status, direction, or passenger-type values until the
  schema change is reviewed.

## Revision evidence

Comparing the November release to October on the revision key produced:

| Change type | Facts |
|---|---:|
| Added | 2,214 |
| Removed | 1,079 |
| Revised | 24,279 |
| Unchanged | 331,740 |

The comparison covers 359,312 keys. October 2024 headline arrivals changed from
10,600 to 10,454, a delta of -146.

## Reproducing the profile

The complete source files are intentionally excluded from Git. Run the local
pipeline against both pinned source files, then inspect each quality manifest
and the second snapshot's revision summary. Record the source URL and SHA-256
before accepting any new figures into this document.
