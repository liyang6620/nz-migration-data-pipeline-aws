"""Locally executable implementation of the migration pipeline."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .contracts import MONTH_PATTERN, ContractViolation
from .ingest import (
    ReleaseConflict,
    acquire_source,
    atomic_replace_directory,
    atomic_write_json,
    preserve_raw_release,
    validate_release_id,
)
from .parsers import parse_source_csv
from .quality import build_quality_report
from .revisions import (
    build_revision_summary,
    compare_snapshots,
    find_previous_snapshot,
    read_snapshot,
)
from .transform import transform_source


@dataclass(frozen=True)
class PipelineResult:
    status: str
    release_id: str
    snapshot_month: str
    source_sha256: str
    row_count: int
    partition_count: int
    output_path: str
    run_id: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(timestamp: datetime) -> str:
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _completion_path(root: Path, release_id: str) -> Path:
    return root / "metadata" / "releases" / f"{release_id}.json"


def _read_completion(root: Path, release_id: str) -> dict[str, object] | None:
    path = _completion_path(root, release_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_curated_snapshot(
    frame: pl.DataFrame,
    root: Path,
    snapshot_month: str,
    success_marker: dict[str, object],
    quality_report: dict[str, object],
    revision_frame: pl.DataFrame | None,
    revision_summary: dict[str, object] | None,
) -> tuple[Path, int]:
    dataset_root = root / "curated" / "migration_arrivals"
    destination = dataset_root / f"snapshot_month={snapshot_month}"
    if destination.exists():
        raise ReleaseConflict(
            f"curated snapshot partition already exists: {snapshot_month}"
        )
    dataset_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=dataset_root))
    try:
        months = frame.get_column("year_month").unique().sort().to_list()
        for year_month in months:
            partition = staging / f"year_month={year_month}"
            partition.mkdir()
            frame.filter(pl.col("year_month") == year_month).write_parquet(
                partition / "part-00000.parquet",
                compression="zstd",
                statistics=True,
            )
        atomic_write_json(staging / "_QUALITY.json", quality_report)
        if revision_frame is not None and revision_summary is not None:
            revision_dir = staging / "_revisions"
            revision_dir.mkdir()
            revision_frame.write_parquet(
                revision_dir / "part-00000.parquet",
                compression="zstd",
                statistics=True,
            )
            atomic_write_json(revision_dir / "summary.json", revision_summary)
        atomic_write_json(staging / "_SUCCESS.json", success_marker)
        atomic_replace_directory(staging, destination)
        return destination, len(months)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _recover_committed_snapshot(
    root: Path,
    *,
    release_id: str,
    snapshot_month: str,
    source_sha256: str,
) -> PipelineResult | None:
    """Recover when data committed but process stopped before metadata commit."""

    output_path = (
        root
        / "curated"
        / "migration_arrivals"
        / f"snapshot_month={snapshot_month}"
    )
    if not output_path.exists():
        return None
    marker_path = output_path / "_SUCCESS.json"
    if not marker_path.is_file():
        raise ReleaseConflict(f"curated snapshot has no success marker: {snapshot_month}")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("release_id") != release_id:
        raise ReleaseConflict(
            f"snapshot_month {snapshot_month!r} belongs to another release_id"
        )
    if marker.get("source_sha256") != source_sha256:
        raise ReleaseConflict(
            f"snapshot_month {snapshot_month!r} has a different SHA-256"
        )
    return PipelineResult(
        status="skipped",
        release_id=release_id,
        snapshot_month=snapshot_month,
        source_sha256=source_sha256,
        row_count=int(marker["row_count"]),
        partition_count=int(marker["partition_count"]),
        output_path=str(output_path),
        run_id=str(marker["run_id"]),
    )


def run_local_pipeline(
    *,
    source: str | Path,
    release_id: str,
    snapshot_month: str,
    output_root: str | Path,
    expected_sha256: str | None = None,
    now: datetime | None = None,
) -> PipelineResult:
    """Run one release locally with immutable inputs and idempotent outputs."""

    validate_release_id(release_id)
    if not MONTH_PATTERN.fullmatch(snapshot_month):
        raise ContractViolation("snapshot_month must use YYYY-MM format")
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    acquired = acquire_source(source)
    if expected_sha256 and acquired.sha256 != expected_sha256:
        raise ContractViolation(
            f"source SHA-256 mismatch: expected {expected_sha256}, got {acquired.sha256}"
        )

    completed = _read_completion(root, release_id)
    if completed:
        if completed.get("source_sha256") != acquired.sha256:
            raise ReleaseConflict(
                f"release_id {release_id!r} is complete with a different SHA-256"
            )
        if completed.get("snapshot_month") != snapshot_month:
            raise ReleaseConflict(
                f"release_id {release_id!r} is complete for a different snapshot_month"
            )
        verified = _recover_committed_snapshot(
            root,
            release_id=release_id,
            snapshot_month=snapshot_month,
            source_sha256=acquired.sha256,
        )
        if not verified:
            raise ReleaseConflict(
                f"completion metadata exists without curated data: {release_id}"
            )
        if verified.run_id != completed.get("run_id"):
            raise ReleaseConflict(f"completion metadata disagrees with data: {release_id}")
        return verified

    started = now or _utc_now()
    ingested_at = _iso_z(started)
    run_id = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    raw_path = preserve_raw_release(
        root,
        release_id=release_id,
        snapshot_month=snapshot_month,
        acquired=acquired,
        ingested_at=ingested_at,
    )
    recovered = _recover_committed_snapshot(
        root,
        release_id=release_id,
        snapshot_month=snapshot_month,
        source_sha256=acquired.sha256,
    )
    if recovered:
        committed = json.loads(
            (Path(recovered.output_path) / "_SUCCESS.json").read_text(
                encoding="utf-8"
            )
        )
        recovered_payload = {
            **asdict(recovered),
            "status": "processed",
            "completed_at": committed["completed_at"],
            "recovered_at": ingested_at,
        }
        atomic_write_json(
            root / "metadata" / "runs" / f"{recovered.run_id}.json",
            recovered_payload,
        )
        atomic_write_json(_completion_path(root, release_id), recovered_payload)
        return recovered

    source_frame = parse_source_csv(raw_path)
    canonical = transform_source(
        source_frame,
        snapshot_month=snapshot_month,
        release_id=release_id,
        source_sha256=acquired.sha256,
        ingested_at=ingested_at,
    )
    quality_report = build_quality_report(canonical)
    previous_path = find_previous_snapshot(root, snapshot_month)
    revision_frame = None
    revision_summary = None
    previous_snapshot_month = None
    if previous_path:
        previous_snapshot_month = previous_path.name.removeprefix("snapshot_month=")
        revision_frame = compare_snapshots(read_snapshot(previous_path), canonical)
        revision_summary = build_revision_summary(
            revision_frame,
            previous_snapshot_month=previous_snapshot_month,
            current_snapshot_month=snapshot_month,
        )
    output_path = (
        root
        / "curated"
        / "migration_arrivals"
        / f"snapshot_month={snapshot_month}"
    )
    success_marker = {
        "release_id": release_id,
        "snapshot_month": snapshot_month,
        "source_sha256": acquired.sha256,
        "row_count": canonical.height,
        "partition_count": canonical.get_column("year_month").n_unique(),
        "output_path": str(output_path),
        "run_id": run_id,
        "completed_at": ingested_at,
        "quality_status": quality_report["quality_status"],
        "previous_snapshot_month": previous_snapshot_month,
        "revision_change_counts": (
            revision_summary["change_counts"] if revision_summary else None
        ),
    }
    output_path, partition_count = _write_curated_snapshot(
        canonical,
        root,
        snapshot_month,
        success_marker,
        quality_report,
        revision_frame,
        revision_summary,
    )
    result = PipelineResult(
        status="processed",
        release_id=release_id,
        snapshot_month=snapshot_month,
        source_sha256=acquired.sha256,
        row_count=canonical.height,
        partition_count=partition_count,
        output_path=str(output_path),
        run_id=run_id,
    )
    payload = {
        **asdict(result),
        "completed_at": _iso_z(now or _utc_now()),
    }
    atomic_write_json(root / "metadata" / "runs" / f"{run_id}.json", payload)
    atomic_write_json(_completion_path(root, release_id), payload)
    return result
