# Data Dictionary – Migration Arrivals Dataset

This document describes the curated dataset produced by the pipeline and used for reporting.

---

## Dataset

**Table:** `nz_migration.migration_arrivals_monthly`  
**Format:** Parquet  
**Partition:** `year_month`

---

## Fields

### year_month
- **Type:** string (YYYY-MM)
- **Description:** Reporting month of migration activity

---

### snapshot_month
- **Type:** string (YYYY-MM)
- **Description:** Source release snapshot used for this record
- **Purpose:** Enables reproducible reporting across revised data releases

---

### direction
- **Type:** string
- **Values:** Arrivals / Departures
- **Description:** Migration flow direction

---

### passenger_type
- **Type:** string
- **Values:** Long-term migrant / Short-term
- **Description:** Migrant classification

---

### citizenship
- **Type:** string
- **Description:** Citizenship category of migrant

---

### visa
- **Type:** string
- **Description:** Visa category of migrant

---

### country_of_residence
- **Type:** string
- **Description:** Last country of residence before migration

---

### estimate
- **Type:** integer
- **Description:** Estimated number of migrants

---

### standard_error
- **Type:** double
- **Description:** Statistical uncertainty measure provided by Stats NZ

---

## Notes

- Records marked as `TOTAL` represent aggregated categories.
- Reporting views exclude `TOTAL` where breakdown analysis is required.
