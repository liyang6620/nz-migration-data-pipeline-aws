"""Acquire source bytes and preserve an immutable raw release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class ReleaseConflict(RuntimeError):
    """Raised when an immutable release ID is reused for different content."""


@dataclass(frozen=True)
class AcquiredSource:
    content: bytes
    source_uri: str
    sha256: str


def atomic_replace_directory(source: Path, destination: Path) -> None:
    """Rename a directory atomically, tolerating brief Windows file locks."""

    for attempt in range(6):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def validate_release_id(release_id: str) -> None:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError(
            "release_id must contain only letters, numbers, dots, underscores, and "
            "hyphens (maximum 200 characters)"
        )


def acquire_source(
    source: str | Path,
    *,
    timeout_seconds: int = 60,
    max_bytes: int = 200 * 1024 * 1024,
) -> AcquiredSource:
    """Read a local CSV or download an HTTP(S) source into memory."""

    source_text = str(source)
    parsed = urlparse(source_text)
    is_windows_path = len(parsed.scheme) == 1 and source_text[1:3] in {":\\", ":/"}
    if isinstance(source, Path) or not parsed.scheme or is_windows_path:
        path = Path(source).expanduser().resolve()
        if path.stat().st_size > max_bytes:
            raise ValueError(f"source exceeds the {max_bytes}-byte size limit")
        content = path.read_bytes()
        source_uri = path.as_uri()
    elif parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(
            source_text,
            headers={"User-Agent": "nz-migration-data-pipeline/0.2"},
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content = response.read(max_bytes + 1)
            source_uri = response.geturl()
        if len(content) > max_bytes:
            raise ValueError(f"source exceeds the {max_bytes}-byte size limit")
    else:
        raise ValueError(f"unsupported source scheme: {parsed.scheme!r}")

    return AcquiredSource(
        content=content,
        source_uri=source_uri,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def preserve_raw_release(
    root: Path,
    *,
    release_id: str,
    snapshot_month: str,
    acquired: AcquiredSource,
    ingested_at: str,
) -> Path:
    """Persist source data once and reject release ID/content conflicts."""

    validate_release_id(release_id)
    raw_root = root / "raw"
    release_dir = raw_root / f"release_id={release_id}"
    source_path = release_dir / "source.csv"
    manifest_path = release_dir / "manifest.json"

    if source_path.exists() or manifest_path.exists():
        if not source_path.is_file() or not manifest_path.is_file():
            raise ReleaseConflict(f"incomplete immutable raw release: {release_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if stored_digest != manifest.get("source_sha256"):
            raise ReleaseConflict(f"stored raw source is corrupt: {release_id}")
        if acquired.sha256 != stored_digest:
            raise ReleaseConflict(
                f"release_id {release_id!r} already exists with a different SHA-256"
            )
        if manifest.get("snapshot_month") != snapshot_month:
            raise ReleaseConflict(
                f"release_id {release_id!r} already uses snapshot_month "
                f"{manifest.get('snapshot_month')!r}"
            )
        return source_path

    raw_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{release_id}-", dir=raw_root))
    try:
        atomic_write_bytes(staging / "source.csv", acquired.content)
        atomic_write_json(
            staging / "manifest.json",
            {
                "byte_size": len(acquired.content),
                "ingested_at": ingested_at,
                "release_id": release_id,
                "snapshot_month": snapshot_month,
                "source_sha256": acquired.sha256,
                "source_uri": acquired.source_uri,
            },
        )
        atomic_replace_directory(staging, release_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return source_path
