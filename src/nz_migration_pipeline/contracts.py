"""Canonical record contract shared by local and AWS pipeline implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from math import isfinite

SCHEMA_VERSION = "1.0.0"
TOTAL = "TOTAL"
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

SOURCE_COLUMNS = (
    "year_month",
    "month_of_release",
    "passenger_type",
    "direction",
    "citizenship",
    "visa",
    "country_of_residence",
    "estimate",
    "standard_error",
    "status",
)

CANONICAL_COLUMNS = (
    "release_id",
    "snapshot_month",
    "source_release_month",
    "year_month",
    "passenger_type",
    "direction",
    "citizenship",
    "visa",
    "country_of_residence",
    "metric_slice",
    "estimate",
    "standard_error",
    "status",
    "source_sha256",
    "ingested_at",
    "schema_version",
)

_SLICE_BY_ACTIVE_DIMENSIONS = {
    (): "total",
    ("citizenship",): "citizenship",
    ("visa",): "visa",
    ("country_of_residence",): "country_of_residence",
    ("citizenship", "visa"): "citizenship_visa",
    ("citizenship", "country_of_residence"): "citizenship_country_of_residence",
    ("visa", "country_of_residence"): "visa_country_of_residence",
    (
        "citizenship",
        "visa",
        "country_of_residence",
    ): "citizenship_visa_country_of_residence",
}
METRIC_SLICES = frozenset(_SLICE_BY_ACTIVE_DIMENSIONS.values())


class ContractViolation(ValueError):
    """Raised when a source or canonical record violates the data contract."""


def _require_month(value: str, field: str) -> None:
    if not MONTH_PATTERN.fullmatch(value):
        raise ContractViolation(f"{field} must use YYYY-MM format: {value!r}")


def _parse_int(value: object, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{field} must be an integer: {value!r}") from exc
    if parsed < 0:
        raise ContractViolation(f"{field} must be non-negative: {parsed}")
    return parsed


def _parse_float(value: object, field: str) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{field} must be numeric: {value!r}") from exc
    if not isfinite(parsed):
        raise ContractViolation(f"{field} must be finite: {value!r}")
    if parsed < 0:
        raise ContractViolation(f"{field} must be non-negative: {parsed}")
    return parsed


def derive_metric_slice(record: Mapping[str, object]) -> str:
    """Classify which dimensions are active rather than aggregated to TOTAL."""

    dimensions = ("citizenship", "visa", "country_of_residence")
    missing = [field for field in dimensions if not str(record.get(field, "")).strip()]
    if missing:
        raise ContractViolation(
            f"dimension values cannot be empty: {', '.join(missing)}"
        )
    active = tuple(field for field in dimensions if record[field] != TOTAL)
    return _SLICE_BY_ACTIVE_DIMENSIONS[active]


def canonicalize_source_row(
    source: Mapping[str, object],
    *,
    snapshot_month: str,
    release_id: str,
    source_sha256: str,
    ingested_at: str,
) -> dict[str, object]:
    """Convert one Stats NZ source row into the canonical versioned fact record."""

    missing = [field for field in SOURCE_COLUMNS if field not in source]
    if missing:
        raise ContractViolation(f"source row is missing columns: {', '.join(missing)}")
    unexpected = [field for field in source if field not in SOURCE_COLUMNS]
    if unexpected:
        raise ContractViolation(
            f"source row has unexpected columns: {', '.join(map(str, unexpected))}"
        )

    record: dict[str, object] = {
        "release_id": release_id,
        "snapshot_month": snapshot_month,
        "source_release_month": str(source["month_of_release"]),
        "year_month": str(source["year_month"]),
        "passenger_type": str(source["passenger_type"]),
        "direction": str(source["direction"]),
        "citizenship": str(source["citizenship"]),
        "visa": str(source["visa"]),
        "country_of_residence": str(source["country_of_residence"]),
        "metric_slice": derive_metric_slice(source),
        "estimate": _parse_int(source["estimate"], "estimate"),
        "standard_error": _parse_float(source["standard_error"], "standard_error"),
        "status": str(source["status"]),
        "source_sha256": source_sha256,
        "ingested_at": ingested_at,
        "schema_version": SCHEMA_VERSION,
    }
    validate_canonical_record(record)
    return record


def validate_canonical_record(record: Mapping[str, object]) -> None:
    missing = [field for field in CANONICAL_COLUMNS if field not in record]
    if missing:
        raise ContractViolation(
            f"canonical record is missing fields: {', '.join(missing)}"
        )

    for field in ("snapshot_month", "source_release_month", "year_month"):
        _require_month(str(record[field]), field)
    if str(record["source_release_month"]) > str(record["snapshot_month"]):
        raise ContractViolation("source_release_month cannot be after snapshot_month")
    if str(record["year_month"]) > str(record["snapshot_month"]):
        raise ContractViolation("year_month cannot be after snapshot_month")

    if record["passenger_type"] != "Long-term migrant":
        raise ContractViolation("this dataset only supports Long-term migrant records")
    if record["direction"] != "Arrivals":
        raise ContractViolation("this source dataset only supports Arrivals")
    if record["status"] not in {"Final", "Provisional"}:
        raise ContractViolation(f"unsupported status: {record['status']!r}")

    expected_slice = derive_metric_slice(record)
    if record["metric_slice"] != expected_slice:
        raise ContractViolation(
            f"metric_slice {record['metric_slice']!r} does not match {expected_slice!r}"
        )
    _parse_int(record["estimate"], "estimate")
    _parse_float(record["standard_error"], "standard_error")

    if not str(record["release_id"]).strip():
        raise ContractViolation("release_id cannot be empty")
    if not SHA256_PATTERN.fullmatch(str(record["source_sha256"])):
        raise ContractViolation("source_sha256 must be a lowercase SHA-256 hex digest")
    try:
        timestamp = datetime.fromisoformat(
            str(record["ingested_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ContractViolation("ingested_at must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ContractViolation("ingested_at must include a timezone")
    if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
        raise ContractViolation("ingested_at must use UTC")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ContractViolation(
            f"unsupported schema_version: {record['schema_version']!r}"
        )


def record_key(record: Mapping[str, object]) -> tuple[object, ...]:
    """Unique key for a fact inside the immutable snapshot history."""

    return (
        record["snapshot_month"],
        record["year_month"],
        record["passenger_type"],
        record["direction"],
        record["citizenship"],
        record["visa"],
        record["country_of_residence"],
    )


def revision_key(record: Mapping[str, object]) -> tuple[object, ...]:
    """Stable key used to compare the same fact across two snapshots."""

    return record_key(record)[1:]
