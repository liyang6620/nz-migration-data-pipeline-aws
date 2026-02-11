-- =====================================================
-- NZ Migration Reporting Semantic Layer (Athena)
-- These views define the official reporting logic used
-- by the Analytics & Reporting team.
-- =====================================================


-- =====================================================
-- 1) Base Fact View
-- Clean, analytics-ready arrivals dataset
-- =====================================================
CREATE OR REPLACE VIEW vw_arrivals_facts AS
SELECT
    year_month,
    citizenship,
    visa,
    country_of_residence,
    estimate AS estimate_arrivals,
    standard_error
FROM nz_migration.migration_arrivals_monthly;



-- =====================================================
-- 2) Monthly KPI View
-- Core reporting metric used in KPI packs
-- =====================================================
CREATE OR REPLACE VIEW vw_arrivals_monthly_kpi AS
SELECT
    year_month,
    SUM(estimate) AS arrivals
FROM nz_migration.migration_arrivals_monthly
GROUP BY year_month
ORDER BY year_month;



-- =====================================================
-- 3) Arrivals by Country of Residence (Monthly)
-- Used for country-level migration trend analysis
-- =====================================================
CREATE OR REPLACE VIEW vw_arrivals_by_country_monthly AS
SELECT
    year_month,
    country_of_residence,
    SUM(estimate) AS arrivals
FROM nz_migration.migration_arrivals_monthly
WHERE country_of_residence <> 'TOTAL'
GROUP BY year_month, country_of_residence
ORDER BY year_month, arrivals DESC;



-- =====================================================
-- 4) Arrivals by Visa Type (Monthly)
-- Used for visa category breakdown reporting
-- =====================================================
CREATE OR REPLACE VIEW vw_arrivals_by_visa_monthly AS
SELECT
    year_month,
    visa,
    SUM(estimate) AS arrivals
FROM nz_migration.migration_arrivals_monthly
WHERE visa <> 'TOTAL'
GROUP BY year_month, visa
ORDER BY year_month, arrivals DESC;
