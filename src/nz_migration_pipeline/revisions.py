"""Revision comparison between immutable Stats NZ snapshots."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl


REVISION_KEY = (
    "year_month",
    "passenger_type",
    "direction",
    "citizenship",
    "visa",
    "country_of_residence",
)
COMPARE_COLUMNS = (
    "source_release_month",
    "metric_slice",
    "estimate",
    "standard_error",
    "status",
)


def find_previous_snapshot(root: Path, current_snapshot_month: str) -> Path | None:
    dataset = root / "curated" / "migration_arrivals"
    if not dataset.exists():
        return None
    candidates = []
    for path in dataset.glob("snapshot_month=*"):
        month = path.name.removeprefix("snapshot_month=")
        if month < current_snapshot_month and (path / "_SUCCESS.json").is_file():
            candidates.append((month, path))
    return max(candidates, default=(None, None))[1]


def read_snapshot(path: Path) -> pl.DataFrame:
    files = sorted(path.glob("year_month=*/part-*.parquet"))
    if not files:
        raise ValueError(f"snapshot contains no Parquet facts: {path}")
    return pl.read_parquet(files)


def compare_snapshots(previous: pl.DataFrame, current: pl.DataFrame) -> pl.DataFrame:
    """Full-join two snapshots and label added, removed, revised, unchanged facts."""

    previous_values = previous.select(
        *REVISION_KEY,
        *[
            pl.col(column).alias(f"previous_{column}")
            for column in COMPARE_COLUMNS
        ],
    )
    current_values = current.select(
        *REVISION_KEY,
        *[pl.col(column).alias(f"current_{column}") for column in COMPARE_COLUMNS],
    )
    joined = previous_values.join(
        current_values,
        on=REVISION_KEY,
        how="full",
        coalesce=True,
    )
    changed = pl.any_horizontal(
        [
            pl.col(f"previous_{column}").ne_missing(
                pl.col(f"current_{column}")
            )
            for column in COMPARE_COLUMNS
        ]
    )
    return (
        joined.with_columns(
            (pl.col("current_estimate") - pl.col("previous_estimate")).alias(
                "estimate_delta"
            ),
            (
                pl.col("current_standard_error")
                - pl.col("previous_standard_error")
            ).alias("standard_error_delta"),
            pl.when(pl.col("previous_estimate").is_null())
            .then(pl.lit("added"))
            .when(pl.col("current_estimate").is_null())
            .then(pl.lit("removed"))
            .when(changed)
            .then(pl.lit("revised"))
            .otherwise(pl.lit("unchanged"))
            .alias("change_type"),
        )
        .sort(REVISION_KEY)
    )


def build_revision_summary(
    revisions: pl.DataFrame,
    *,
    previous_snapshot_month: str,
    current_snapshot_month: str,
) -> dict[str, object]:
    counts = Counter(revisions.get_column("change_type").to_list())
    revised = revisions.filter(pl.col("change_type") == "revised")
    total_revised = revised.filter(
        pl.col("current_metric_slice").fill_null(pl.col("previous_metric_slice"))
        == "total"
    )
    max_delta = revisions.get_column("estimate_delta").abs().max()
    return {
        "previous_snapshot_month": previous_snapshot_month,
        "current_snapshot_month": current_snapshot_month,
        "row_count": revisions.height,
        "change_counts": {
            change: counts.get(change, 0)
            for change in ("added", "removed", "revised", "unchanged")
        },
        "revised_total_slice_count": total_revised.height,
        "maximum_absolute_estimate_delta": max_delta,
    }
