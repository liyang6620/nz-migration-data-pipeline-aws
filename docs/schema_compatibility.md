# Schema compatibility policy

The canonical schema version is 1.0.0. Source changes are rejected by default
until their consumer impact is understood.

## Compatible changes

The following can be released as a backward-compatible minor version:

- a new nullable metadata column that is not part of a business key;
- a new Gold view;
- a new quality rule that does not change valid historical output;
- additional source-domain values after profiling and documentation.

Compatible changes require tests, an updated data dictionary, a successful
backfill sample, and a Gold query smoke test.

## Breaking changes

The following require a new major schema version and a migration plan:

- removing or renaming a canonical column;
- changing a column type;
- changing the canonical or revision key;
- changing metric_slice semantics;
- replacing a committed snapshot;
- changing a Gold view's existing columns or grain.

Breaking output must be published to a new table or view name. Existing
consumers keep the old interface until an explicit retirement date.

## Source drift response

An unexpected header, missing required value, new passenger type, new
direction, unsupported status, invalid month, or duplicate key fails the Glue
job and creates quarantine evidence. Operators do not edit the file in place.
They verify the publisher's release notes, profile the new domain, update the
contract and tests, and replay the original S3 object version.
