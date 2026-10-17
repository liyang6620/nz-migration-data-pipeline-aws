# AWS deployment evidence

This record links repository claims to a live, sanitised deployment validation.
Account identifiers, bucket names, email addresses, and Terraform state are
intentionally excluded. The deployment is in `ap-southeast-2`.

## Verification record

The following checks were completed on 18 October 2026 NZDT against the AWS
runtime represented by the current Terraform configuration.

| Control | Observed result |
|---|---|
| October release | Step Functions `SUCCEEDED`; 357,098 rows committed |
| November release | Step Functions `SUCCEEDED`; 358,233 rows committed |
| Latest consumer snapshot | `2025-11`; 358,233 rows through the Gold view |
| Pipeline quality | `passed` for both committed snapshots |
| November Glue run | `SUCCEEDED`; 196 seconds |
| Candidate publication area | Empty after atomic promotion |
| Run registry | November execution recorded as `SUCCEEDED` |
| Audit evidence | Immutable versioned audit object present |
| Terraform drift | `No changes`; detailed exit code `0` |
| Failure notifications | SNS email subscription confirmed |

Latest source SHA-256:

~~~text
976a8f3980ce033840fb7d02236fd72289072bd37fb06631e1f15adf49313ae0
~~~

The November Step Functions execution stopped successfully at
`2026-10-17T22:45:21.396Z`. Its Glue run ID was:

~~~text
jr_4c3a6be65a6df101399dfe3e1442a170408a4446e8be9b051430ddb6fd4777f9
~~~

These identifiers are operational evidence, not credentials.

## Consumer validation

`vw_release_history` returned:

| snapshot_month | release_id | status | row_count |
|---|---|---|---:|
| 2025-10 | stats-nz-international-migration-2025-10 | SUCCEEDED | 357,098 |
| 2025-11 | stats-nz-international-migration-2025-11 | SUCCEEDED | 358,233 |

`vw_revision_summary` for the November snapshot returned:

| current | previous | added | removed | revised | unchanged |
|---|---|---:|---:|---:|---:|
| 2025-11 | 2025-10 | 2,214 | 1,079 | 24,279 | 331,740 |

The total revision-key population is 359,312. The counts reconcile exactly to
that population.

## Reproduction queries

Run these inside the managed `nz-migration-v2` Athena workgroup:

~~~sql
SELECT snapshot_month, release_id, status, row_count
FROM nz_migration_v2_gold.vw_release_history
ORDER BY snapshot_month;

SELECT snapshot_month, quality_status
FROM nz_migration_v2_gold.vw_pipeline_quality
ORDER BY snapshot_month;

SELECT current_snapshot, previous_snapshot, added_facts, removed_facts,
       revised_facts, unchanged_facts
FROM nz_migration_v2_gold.vw_revision_summary
WHERE current_snapshot = '2025-11';
~~~

Verify infrastructure drift with a reviewed, authenticated environment:

~~~bash
terraform -chdir=infrastructure/terraform plan \
  -detailed-exitcode \
  -var='alert_email=<confirmed-address>'
~~~

Exit code `0` means the real infrastructure matches the repository. Do not
commit the address, generated plan, state, or provider credentials.

## Evidence boundary

The production validation image in the README is a sanitised visual summary of
the live results above. It is not an AWS Console screenshot. This avoids
publishing account identifiers while keeping every material claim reproducible
through the listed views and commands.

## Updating the validation image

`docs/assets/production-validation.html` is the editable source for the README
image. Render it at exactly 1600 by 900 pixels after repeating the checks in
this document, then replace `production-validation.png`. Keep the verification
date visible and never add account IDs, bucket names, email addresses, query
results containing personal data, or credentials to either asset.

