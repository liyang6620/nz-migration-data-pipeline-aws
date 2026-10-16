# ADR 003: Publish immutable snapshots with a commit marker

- Status: Accepted
- Date: 2026-10-16

## Context

Neither a local filesystem nor S3 provides a transaction spanning hundreds of
partition files and metadata objects. Consumers must never treat a partially
written snapshot as complete.

## Decision

Local execution writes the entire snapshot to a sibling temporary directory and
renames it atomically. AWS execution uploads to a run-scoped staging prefix,
copies all data and evidence to the deterministic final prefix, and copies
`_SUCCESS.json` last.

Readers and revision discovery consider only snapshot prefixes containing a
valid `_SUCCESS.json`. A matching committed release is a no-op; a conflicting
release ID, snapshot month, or SHA-256 fails rather than overwriting history.

## Consequences

- Data, quality evidence, and revision evidence become visible as one logical
  publication.
- Retries can repair missing run metadata from the committed marker.
- S3 publication uses extra COPY and DELETE requests, acceptable for a monthly
  dataset of this size.
- A failed pre-commit run can leave staging objects. They are isolated from
  readers and can be expired or removed by operations tooling.
