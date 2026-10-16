"""Vectorised transformation from the source cube to canonical facts."""

from __future__ import annotations

import polars as pl

from .contracts import CANONICAL_COLUMNS, SCHEMA_VERSION, ContractViolation

DIMENSIONS = ("citizenship", "visa", "country_of_residence")
BUSINESS_KEY = (
    "snapshot_month",
    "year_month",
    "passenger_type",
    "direction",
    *DIMENSIONS,
)


def _raise_when(frame: pl.DataFrame, expression: pl.Expr, message: str) -> None:
    if frame.select(expression.any()).item():
        raise ContractViolation(message)


def transform_source(
    source: pl.DataFrame,
    *,
    snapshot_month: str,
    release_id: str,
    source_sha256: str,
    ingested_at: str,
) -> pl.DataFrame:
    """Validate and transform an entire source release using Polars expressions."""

    text_columns = [
        "year_month",
        "month_of_release",
        "passenger_type",
        "direction",
        *DIMENSIONS,
        "estimate",
        "standard_error",
        "status",
    ]
    _raise_when(
        source,
        pl.any_horizontal([pl.col(column).is_null() for column in text_columns]),
        "source contains null values",
    )
    _raise_when(
        source,
        pl.any_horizontal(
            [pl.col(column).str.strip_chars().eq("") for column in text_columns]
        ),
        "source contains empty values",
    )

    month_pattern = r"^\d{4}-(0[1-9]|1[0-2])$"
    for column in ("year_month", "month_of_release"):
        _raise_when(
            source,
            ~pl.col(column).str.contains(month_pattern),
            f"{column} must use YYYY-MM format",
        )
    _raise_when(
        source,
        pl.col("month_of_release") > pl.lit(snapshot_month),
        "source_release_month cannot be after snapshot_month",
    )
    _raise_when(
        source,
        pl.col("year_month") > pl.lit(snapshot_month),
        "year_month cannot be after snapshot_month",
    )
    _raise_when(
        source,
        pl.col("passenger_type") != "Long-term migrant",
        "this dataset only supports Long-term migrant records",
    )
    _raise_when(
        source,
        pl.col("direction") != "Arrivals",
        "this source dataset only supports Arrivals",
    )
    _raise_when(
        source,
        ~pl.col("status").is_in(["Final", "Provisional"]),
        "source contains an unsupported status",
    )

    estimate = pl.col("estimate").cast(pl.Int64, strict=False)
    standard_error = pl.col("standard_error").cast(pl.Float64, strict=False)
    _raise_when(source, estimate.is_null() | (estimate < 0), "invalid estimate")
    _raise_when(
        source,
        standard_error.is_null() | standard_error.is_infinite() | (standard_error < 0),
        "invalid standard_error",
    )

    c_active = pl.col("citizenship") != "TOTAL"
    v_active = pl.col("visa") != "TOTAL"
    r_active = pl.col("country_of_residence") != "TOTAL"
    metric_slice = (
        pl.when(~c_active & ~v_active & ~r_active)
        .then(pl.lit("total"))
        .when(c_active & ~v_active & ~r_active)
        .then(pl.lit("citizenship"))
        .when(~c_active & v_active & ~r_active)
        .then(pl.lit("visa"))
        .when(~c_active & ~v_active & r_active)
        .then(pl.lit("country_of_residence"))
        .when(c_active & v_active & ~r_active)
        .then(pl.lit("citizenship_visa"))
        .when(c_active & ~v_active & r_active)
        .then(pl.lit("citizenship_country_of_residence"))
        .when(~c_active & v_active & r_active)
        .then(pl.lit("visa_country_of_residence"))
        .otherwise(pl.lit("citizenship_visa_country_of_residence"))
    )

    canonical = (
        source.rename({"month_of_release": "source_release_month"})
        .with_columns(
            pl.lit(release_id).alias("release_id"),
            pl.lit(snapshot_month).alias("snapshot_month"),
            metric_slice.alias("metric_slice"),
            estimate.alias("estimate"),
            standard_error.alias("standard_error"),
            pl.lit(source_sha256).alias("source_sha256"),
            pl.lit(ingested_at).alias("ingested_at"),
            pl.lit(SCHEMA_VERSION).alias("schema_version"),
        )
        .select(CANONICAL_COLUMNS)
    )

    if canonical.select(pl.struct(BUSINESS_KEY).is_duplicated().any()).item():
        raise ContractViolation("source contains duplicate canonical business keys")
    return canonical
