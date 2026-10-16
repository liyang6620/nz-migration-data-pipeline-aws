"""Command-line interface for the pipeline."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .local_pipeline import run_local_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nz-migration-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    local = commands.add_parser("run-local", help="process one release locally")
    local.add_argument("--source", required=True, help="local path or HTTPS URL")
    local.add_argument("--release-id", required=True)
    local.add_argument("--snapshot-month", required=True, help="YYYY-MM")
    local.add_argument("--output-root", default=".local/pipeline")
    local.add_argument("--expected-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run-local":
        result = run_local_pipeline(
            source=args.source,
            release_id=args.release_id,
            snapshot_month=args.snapshot_month,
            output_root=args.output_root,
            expected_sha256=args.expected_sha256,
        )
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
