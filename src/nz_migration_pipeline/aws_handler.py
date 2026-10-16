"""AWS Lambda adapters for immutable S3 ingestion and snapshot publication."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .contracts import MONTH_PATTERN, ContractViolation
from .ingest import acquire_source, validate_release_id
from .local_pipeline import _write_curated_snapshot
from .parsers import parse_source_csv
from .quality import build_quality_report
from .revisions import build_revision_summary, compare_snapshots, read_snapshot
from .transform import transform_source

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
S3: Any = None


def _s3_client() -> Any:
    global S3
    if S3 is None:
        S3 = boto3.client("s3")
    return S3


def _iso_z() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _required_event(event: dict[str, Any]) -> tuple[str, str, str]:
    try:
        source_url = str(event["source_url"])
        release_id = str(event["release_id"])
        snapshot_month = str(event["snapshot_month"])
    except KeyError as exc:
        raise ContractViolation(f"missing event field: {exc.args[0]}") from exc
    if not source_url.startswith("https://"):
        raise ContractViolation("source_url must use HTTPS")
    validate_release_id(release_id)
    if not MONTH_PATTERN.fullmatch(snapshot_month):
        raise ContractViolation("snapshot_month must use YYYY-MM format")
    return source_url, release_id, snapshot_month


def _get_json(bucket: str, key: str) -> dict[str, Any] | None:
    try:
        response = _s3_client().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        raise
    return json.loads(response["Body"].read())


def _put_json(bucket: str, key: str, payload: dict[str, Any]) -> None:
    _s3_client().put_object(
        Bucket=bucket,
        Key=key,
        Body=(json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def _head_object(bucket: str, key: str) -> dict[str, Any] | None:
    try:
        return _s3_client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        raise


def _ingest_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Download one official release and commit its immutable raw manifest."""

    bucket = os.environ["DATA_BUCKET"]
    source_url, release_id, snapshot_month = _required_event(event)
    acquired = acquire_source(source_url)
    if not acquired.source_uri.startswith("https://"):
        raise ContractViolation("source redirects must remain on HTTPS")
    expected = event.get("expected_sha256")
    if expected and expected != acquired.sha256:
        raise ContractViolation(
            f"source SHA-256 mismatch: expected {expected}, got {acquired.sha256}"
        )

    prefix = f"raw/release_id={release_id}"
    source_key = f"{prefix}/source.csv"
    manifest_key = f"{prefix}/manifest.json"
    existing = _get_json(bucket, manifest_key)
    if existing:
        if existing.get("source_sha256") != acquired.sha256:
            raise ContractViolation(
                f"release_id {release_id!r} already has different content"
            )
        if existing.get("snapshot_month") != snapshot_month:
            raise ContractViolation(
                f"release_id {release_id!r} already has a different snapshot_month"
            )
        source_head = _head_object(bucket, source_key)
        if not source_head:
            raise ContractViolation(f"raw manifest has no source object: {release_id}")
        if source_head.get("Metadata", {}).get("source-sha256") != acquired.sha256:
            raise ContractViolation(f"raw source metadata is corrupt: {release_id}")
        manifest = existing
        status = "skipped"
    else:
        ingested_at = _iso_z()
        source_head = _head_object(bucket, source_key)
        if source_head:
            if source_head.get("Metadata", {}).get("source-sha256") != acquired.sha256:
                raise ContractViolation(
                    f"uncommitted raw source differs for release_id {release_id!r}"
                )
        else:
            _s3_client().put_object(
                Bucket=bucket,
                Key=source_key,
                Body=acquired.content,
                ContentType="text/csv",
                ServerSideEncryption="AES256",
                Metadata={"source-sha256": acquired.sha256},
            )
        manifest = {
            "byte_size": len(acquired.content),
            "ingested_at": ingested_at,
            "release_id": release_id,
            "snapshot_month": snapshot_month,
            "source_sha256": acquired.sha256,
            "source_uri": acquired.source_uri,
            "source_key": source_key,
        }
        _put_json(bucket, manifest_key, manifest)
        status = "processed"

    LOGGER.info(
        "raw release committed",
        extra={"release_id": release_id, "source_sha256": acquired.sha256},
    )
    return {**manifest, "ingest_status": status}


def _record_failure(
    stage: str,
    event: dict[str, Any],
    context: Any,
    exc: Exception,
) -> None:
    failure_id = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    )
    payload = {
        "failure_id": failure_id,
        "failed_at": _iso_z(),
        "stage": stage,
        "release_id": event.get("release_id"),
        "snapshot_month": event.get("snapshot_month"),
        "source_sha256": event.get("source_sha256"),
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "lambda_request_id": getattr(context, "aws_request_id", None),
    }
    try:
        _put_json(
            os.environ["DATA_BUCKET"],
            f"quarantine/{stage}/{failure_id}.json",
            payload,
        )
    except Exception:
        LOGGER.exception("failed to persist quarantine record")
    LOGGER.exception("pipeline stage failed", extra=payload)


def ingest_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run ingestion and retain structured failure evidence on rejection."""

    try:
        return _ingest_handler(event, context)
    except Exception as exc:
        _record_failure("ingest", event, context, exc)
        raise


def _list_successful_snapshots(bucket: str, before_month: str) -> list[str]:
    paginator = _s3_client().get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=bucket,
        Prefix="curated/migration_arrivals/",
        Delimiter="/",
    )
    months = []
    for page in pages:
        for item in page.get("CommonPrefixes", []):
            name = item["Prefix"].rstrip("/").rsplit("/", 1)[-1]
            month = name.removeprefix("snapshot_month=")
            if MONTH_PATTERN.fullmatch(month) and month < before_month:
                marker = _get_json(bucket, f"{item['Prefix']}_SUCCESS.json")
                if marker:
                    months.append(month)
    return sorted(months)


def _download_snapshot(bucket: str, snapshot_month: str, destination: Path) -> None:
    prefix = f"curated/migration_arrivals/snapshot_month={snapshot_month}/"
    paginator = _s3_client().get_paginator("list_objects_v2")
    found = False
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if "/year_month=" not in key or not key.endswith(".parquet"):
                continue
            relative = key.removeprefix(prefix)
            local_path = destination / relative
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _s3_client().download_file(bucket, key, str(local_path))
            found = True
    if not found:
        raise ContractViolation(
            f"previous snapshot {snapshot_month} has no Parquet facts"
        )


def _upload_snapshot(
    bucket: str,
    local_snapshot: Path,
    snapshot_month: str,
    run_id: str,
) -> None:
    final_prefix = f"curated/migration_arrivals/snapshot_month={snapshot_month}/"
    staging_prefix = f"staging/run_id={run_id}/"
    files = [path for path in local_snapshot.rglob("*") if path.is_file()]
    success = next(path for path in files if path.name == "_SUCCESS.json")
    ordered = [path for path in files if path != success] + [success]

    for path in ordered:
        relative = path.relative_to(local_snapshot).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        _s3_client().upload_file(
            str(path),
            bucket,
            f"{staging_prefix}{relative}",
            ExtraArgs={
                "ContentType": content_type,
                "ServerSideEncryption": "AES256",
            },
        )

    existing = _s3_client().list_objects_v2(Bucket=bucket, Prefix=final_prefix)
    if existing.get("KeyCount", 0):
        if _get_json(bucket, f"{final_prefix}_SUCCESS.json"):
            raise ContractViolation(f"snapshot {snapshot_month} is already complete")
        for item in existing.get("Contents", []):
            _s3_client().delete_object(Bucket=bucket, Key=item["Key"])

    for path in ordered:
        relative = path.relative_to(local_snapshot).as_posix()
        _s3_client().copy_object(
            Bucket=bucket,
            Key=f"{final_prefix}{relative}",
            CopySource={"Bucket": bucket, "Key": f"{staging_prefix}{relative}"},
            ServerSideEncryption="AES256",
        )
    for path in files:
        relative = path.relative_to(local_snapshot).as_posix()
        _s3_client().delete_object(Bucket=bucket, Key=f"{staging_prefix}{relative}")


def _transform_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Transform the committed raw object and atomically publish its snapshot."""

    bucket = os.environ["DATA_BUCKET"]
    release_id = str(event["release_id"])
    snapshot_month = str(event["snapshot_month"])
    source_sha256 = str(event["source_sha256"])
    final_marker = (
        f"curated/migration_arrivals/snapshot_month={snapshot_month}/_SUCCESS.json"
    )
    completed = _get_json(bucket, final_marker)
    if completed:
        if (
            completed.get("release_id") != release_id
            or completed.get("source_sha256") != source_sha256
        ):
            raise ContractViolation(
                f"snapshot {snapshot_month} already exists with different content"
            )
        recovered = {**completed, "status": "processed"}
        _put_json(bucket, f"metadata/runs/{completed['run_id']}.json", recovered)
        _put_json(bucket, f"metadata/releases/{release_id}.json", recovered)
        return {**completed, "status": "skipped"}

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        raw_path = root / "source.csv"
        _s3_client().download_file(bucket, str(event["source_key"]), str(raw_path))
        source = parse_source_csv(raw_path)
        canonical = transform_source(
            source,
            snapshot_month=snapshot_month,
            release_id=release_id,
            source_sha256=source_sha256,
            ingested_at=str(event["ingested_at"]),
        )
        quality = build_quality_report(canonical)

        previous_months = _list_successful_snapshots(bucket, snapshot_month)
        previous_month = previous_months[-1] if previous_months else None
        revisions = None
        revision_summary = None
        if previous_month:
            previous_path = root / f"snapshot_month={previous_month}"
            _download_snapshot(bucket, previous_month, previous_path)
            revisions = compare_snapshots(read_snapshot(previous_path), canonical)
            revision_summary = build_revision_summary(
                revisions,
                previous_snapshot_month=previous_month,
                current_snapshot_month=snapshot_month,
            )

        local_pipeline_root = root / "pipeline"
        output_path = (
            local_pipeline_root
            / "curated"
            / "migration_arrivals"
            / f"snapshot_month={snapshot_month}"
        )
        success = {
            "release_id": release_id,
            "snapshot_month": snapshot_month,
            "source_sha256": source_sha256,
            "row_count": canonical.height,
            "partition_count": canonical.get_column("year_month").n_unique(),
            "run_id": run_id,
            "completed_at": _iso_z(),
            "quality_status": quality["quality_status"],
            "previous_snapshot_month": previous_month,
            "revision_change_counts": (
                revision_summary["change_counts"] if revision_summary else None
            ),
        }
        _write_curated_snapshot(
            canonical,
            local_pipeline_root,
            snapshot_month,
            success,
            quality,
            revisions,
            revision_summary,
        )
        _upload_snapshot(bucket, output_path, snapshot_month, run_id)

    result = {**success, "status": "processed"}
    _put_json(bucket, f"metadata/runs/{run_id}.json", result)
    _put_json(bucket, f"metadata/releases/{release_id}.json", result)
    LOGGER.info("curated snapshot published", extra=result)
    return result


def transform_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Publish a release and retain structured failure evidence on rejection."""

    try:
        return _transform_handler(event, context)
    except Exception as exc:
        _record_failure("transform", event, context, exc)
        raise
