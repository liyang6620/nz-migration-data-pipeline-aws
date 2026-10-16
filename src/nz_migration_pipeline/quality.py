"""Data quality evidence produced for every accepted snapshot."""

from __future__ import annotations

from collections import Counter

import polars as pl

from .contracts import SCHEMA_VERSION
from .transform import BUSINESS_KEY


def build_quality_report(frame: pl.DataFrame) -> dict[str, object]:
    """Build deterministic evidence for checks already enforced as blocking."""

    duplicate_count = int(
        frame.select(pl.struct(BUSINESS_KEY).is_duplicated().sum()).item()
    )
    null_count = int(frame.null_count().select(pl.sum_horizontal(pl.all())).item())
    slice_counts = Counter(frame.get_column("metric_slice").to_list())
    status_counts = Counter(frame.get_column("status").to_list())
    checks = [
        {
            "check": "non_empty_release",
            "status": "passed" if frame.height > 0 else "failed",
            "observed": frame.height,
        },
        {
            "check": "canonical_key_unique",
            "status": "passed" if duplicate_count == 0 else "failed",
            "observed": duplicate_count,
        },
        {
            "check": "required_values_non_null",
            "status": "passed" if null_count == 0 else "failed",
            "observed": null_count,
        },
        {
            "check": "total_slice_present",
            "status": "passed" if slice_counts["total"] > 0 else "failed",
            "observed": slice_counts["total"],
        },
    ]
    return {
        "quality_status": (
            "passed"
            if all(check["status"] == "passed" for check in checks)
            else "failed"
        ),
        "schema_version": SCHEMA_VERSION,
        "row_count": frame.height,
        "business_key_count": frame.select(pl.struct(BUSINESS_KEY).n_unique()).item(),
        "activity_month_min": frame.get_column("year_month").min(),
        "activity_month_max": frame.get_column("year_month").max(),
        "source_release_month_min": frame.get_column("source_release_month").min(),
        "source_release_month_max": frame.get_column("source_release_month").max(),
        "metric_slice_counts": dict(sorted(slice_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "checks": checks,
    }
