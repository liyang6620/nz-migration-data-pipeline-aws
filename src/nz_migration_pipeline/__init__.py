"""Core contracts for the NZ migration data pipeline."""

from .contracts import (
    ContractViolation,
    canonicalize_source_row,
    derive_metric_slice,
    record_key,
    revision_key,
    validate_canonical_record,
)
from .local_pipeline import PipelineResult, run_local_pipeline

__all__ = [
    "ContractViolation",
    "canonicalize_source_row",
    "derive_metric_slice",
    "record_key",
    "revision_key",
    "validate_canonical_record",
    "PipelineResult",
    "run_local_pipeline",
]
