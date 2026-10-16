"""Strict parsers for Stats NZ source releases."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .contracts import SOURCE_COLUMNS, ContractViolation


def parse_source_csv(path: Path) -> pl.DataFrame:
    """Load all source values as strings so validation controls every cast."""

    try:
        frame = pl.read_csv(
            path,
            schema_overrides={column: pl.String for column in SOURCE_COLUMNS},
            infer_schema_length=0,
            null_values=[],
        )
    except Exception as exc:
        raise ContractViolation(f"source is not a valid CSV: {exc}") from exc

    actual = frame.columns
    missing = [column for column in SOURCE_COLUMNS if column not in actual]
    unexpected = [column for column in actual if column not in SOURCE_COLUMNS]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected columns: {', '.join(unexpected)}")
        raise ContractViolation("; ".join(details))
    if actual != list(SOURCE_COLUMNS):
        raise ContractViolation("source columns are not in the contracted order")
    if frame.is_empty():
        raise ContractViolation("source contains no data rows")
    return frame
