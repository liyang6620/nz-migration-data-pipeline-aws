-- Revision-safe semantic layer for the V2 canonical source cube.
-- Run in the nz_migration_v2 database using the Terraform-managed workgroup.

CREATE OR REPLACE VIEW vw_arrivals_facts AS
WITH latest AS (
    SELECT max(snapshot_month) AS snapshot_month
    FROM migration_arrivals
)
SELECT facts.*
FROM migration_arrivals AS facts
JOIN latest
  ON facts.snapshot_month = latest.snapshot_month;


-- Exactly one triple-TOTAL fact is expected for each activity month.
CREATE OR REPLACE VIEW vw_arrivals_monthly_kpi AS
SELECT
    snapshot_month,
    year_month,
    estimate AS arrivals,
    standard_error,
    status
FROM vw_arrivals_facts
WHERE metric_slice = 'total';


-- Citizenship and visa remain TOTAL, so each residence is counted once.
CREATE OR REPLACE VIEW vw_arrivals_by_country_monthly AS
SELECT
    snapshot_month,
    year_month,
    country_of_residence,
    estimate AS arrivals,
    standard_error,
    status
FROM vw_arrivals_facts
WHERE metric_slice = 'country_of_residence';


-- Citizenship and residence remain TOTAL, so each visa is counted once.
CREATE OR REPLACE VIEW vw_arrivals_by_visa_monthly AS
SELECT
    snapshot_month,
    year_month,
    visa,
    estimate AS arrivals,
    standard_error,
    status
FROM vw_arrivals_facts
WHERE metric_slice = 'visa';
