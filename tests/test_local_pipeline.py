import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nz_migration_pipeline.ingest import ReleaseConflict  # noqa: E402
from nz_migration_pipeline.ingest import acquire_source  # noqa: E402
from nz_migration_pipeline.local_pipeline import run_local_pipeline  # noqa: E402
from nz_migration_pipeline.contracts import ContractViolation  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "source_snapshot_2025_10.csv"
NOVEMBER_FIXTURE = ROOT / "tests" / "fixtures" / "source_snapshot_2025_11.csv"


class LocalPipelineIntegrationTests(unittest.TestCase):
    def test_source_size_limit_is_enforced_before_local_read(self):
        with self.assertRaisesRegex(ValueError, "size limit"):
            acquire_source(FIXTURE, max_bytes=1)

    def test_processes_partitions_and_skips_an_identical_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = run_local_pipeline(
                source=FIXTURE,
                release_id="fixture-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )
            second = run_local_pipeline(
                source=FIXTURE,
                release_id="fixture-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )

            self.assertEqual("processed", first.status)
            self.assertEqual("skipped", second.status)
            self.assertEqual(first.run_id, second.run_id)
            self.assertEqual(5, first.row_count)
            self.assertEqual(1, first.partition_count)
            self.assertEqual(1, len(list(output.glob("metadata/runs/*.json"))))

            parquet = list(output.glob("curated/**/*.parquet"))
            self.assertEqual(1, len(parquet))
            frame = pl.read_parquet(parquet[0])
            self.assertEqual(5, frame.height)
            self.assertEqual(pl.Int64, frame.schema["estimate"])
            self.assertEqual(pl.Float64, frame.schema["standard_error"])
            total = frame.filter(pl.col("metric_slice") == "total")
            self.assertEqual(1, total.height)
            self.assertEqual(10600, total.get_column("estimate").sum())

            raw_manifest = json.loads(
                next(output.glob("raw/*/manifest.json")).read_text(encoding="utf-8")
            )
            expected_digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
            self.assertEqual(expected_digest, raw_manifest["source_sha256"])

    def test_rejects_changed_content_for_an_existing_release_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pipeline"
            changed = Path(temporary) / "changed.csv"
            run_local_pipeline(
                source=FIXTURE,
                release_id="fixture-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )
            changed.write_bytes(FIXTURE.read_bytes().replace(b"10600", b"10601", 1))
            with self.assertRaisesRegex(ReleaseConflict, "different SHA-256"):
                run_local_pipeline(
                    source=changed,
                    release_id="fixture-2025-10",
                    snapshot_month="2025-10",
                    output_root=output,
                )

    def test_recovers_if_completion_metadata_was_not_committed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = run_local_pipeline(
                source=FIXTURE,
                release_id="recovery-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )
            (output / "metadata" / "releases" / "recovery-2025-10.json").unlink()

            recovered = run_local_pipeline(
                source=FIXTURE,
                release_id="recovery-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )
            self.assertEqual("skipped", recovered.status)
            self.assertEqual(first.run_id, recovered.run_id)
            self.assertTrue(
                (output / "metadata" / "releases" / "recovery-2025-10.json").is_file()
            )

    def test_duplicate_business_keys_fail_without_curated_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pipeline"
            duplicate = ROOT / "tests" / "fixtures" / "invalid_duplicate.csv"
            with self.assertRaisesRegex(ContractViolation, "duplicate"):
                run_local_pipeline(
                    source=duplicate,
                    release_id="duplicate-2025-10",
                    snapshot_month="2025-10",
                    output_root=output,
                )
            self.assertFalse((output / "curated").exists())
            self.assertFalse((output / "metadata").exists())

    def test_emits_quality_evidence_and_revision_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            run_local_pipeline(
                source=FIXTURE,
                release_id="fixture-2025-10",
                snapshot_month="2025-10",
                output_root=output,
            )
            run_local_pipeline(
                source=NOVEMBER_FIXTURE,
                release_id="fixture-2025-11",
                snapshot_month="2025-11",
                output_root=output,
            )

            october = (
                output
                / "curated"
                / "migration_arrivals"
                / "snapshot_month=2025-10"
            )
            november = october.parent / "snapshot_month=2025-11"
            quality = json.loads(
                (november / "_QUALITY.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (november / "_revisions" / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            revisions = pl.read_parquet(
                november / "_revisions" / "part-00000.parquet"
            )

            self.assertEqual("passed", quality["quality_status"])
            self.assertEqual(5, quality["business_key_count"])
            self.assertEqual(5, summary["change_counts"]["revised"])
            self.assertEqual(146, summary["maximum_absolute_estimate_delta"])
            total = revisions.filter(
                (pl.col("current_metric_slice") == "total")
                & (pl.col("year_month") == "2024-10")
            )
            self.assertEqual(-146, total.get_column("estimate_delta").item())
            self.assertTrue((october / "_QUALITY.json").is_file())
            self.assertFalse((october / "_revisions").exists())

    def test_cli_runs_as_a_python_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "nz_migration_pipeline",
                    "run-local",
                    "--source",
                    str(FIXTURE),
                    "--release-id",
                    "cli-2025-10",
                    "--snapshot-month",
                    "2025-10",
                    "--output-root",
                    temporary,
                ],
                cwd=ROOT,
                env={**__import__("os").environ, "PYTHONPATH": str(SRC)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("processed", json.loads(completed.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
