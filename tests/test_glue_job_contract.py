import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB_PATH = ROOT / "Glue" / "jobs" / "process_migration.py"


def load_job_module():
    spec = importlib.util.spec_from_file_location("process_migration", JOB_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GlueJobContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = load_job_module()

    def test_landing_key_carries_snapshot_and_release_identity(self):
        key = (
            "landing/dataset=migration/snapshot_month=2025-11/"
            "release_id=stats-nz-2025-11/source.csv"
        )
        self.assertEqual(
            ("2025-11", "stats-nz-2025-11"), self.job.parse_landing_key(key)
        )

    def test_encoded_landing_key_is_decoded_before_validation(self):
        key = (
            "landing%2Fdataset%3Dmigration%2Fsnapshot_month%3D2025-11%2F"
            "release_id%3Dstats-nz-2025-11%2Fsource.csv"
        )
        self.assertEqual(
            ("2025-11", "stats-nz-2025-11"), self.job.parse_landing_key(key)
        )

    def test_uncontracted_landing_keys_are_rejected(self):
        invalid = (
            "landing/dataset=migration/snapshot_month=2025-11/"
            "release_id=unsafe release/source.csv"
        )
        with self.assertRaisesRegex(self.job.DataContractError, "landing key"):
            self.job.parse_landing_key(invalid)

    def test_all_cube_slices_are_explicitly_supported(self):
        self.assertEqual(8, len(self.job.METRIC_SLICES))
        self.assertIn("total", self.job.METRIC_SLICES)

    def test_source_header_requires_exact_names_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.csv"
            valid.write_text(
                ",".join(self.job.SOURCE_COLUMNS) + "\n", encoding="utf-8-sig"
            )
            self.job._validate_source_header(valid)

            invalid = Path(directory) / "invalid.csv"
            invalid.write_text(
                ",".join((*self.job.SOURCE_COLUMNS, "unexpected")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(self.job.DataContractError, "source columns"):
                self.job._validate_source_header(invalid)

    def test_job_defers_aws_glue_and_spark_imports_until_runtime(self):
        source = JOB_PATH.read_text(encoding="utf-8")
        prefix = source.split("def main()", 1)[0]
        self.assertNotIn("import awsglue", prefix)
        self.assertNotIn("import pyspark", prefix)

    def test_athena_quality_record_is_one_json_object_per_line(self):
        payload = {"quality_status": "passed", "row_count": 357098}
        encoded = self.job._json_record_bytes(payload)
        self.assertEqual(1, encoded.count(b"\n"))
        self.assertEqual(payload, json.loads(encoded))

    def test_commit_and_quality_paths_support_cross_release_queries(self):
        source = JOB_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'metadata/commits/snapshot_month={snapshot_month}/success.json', source
        )
        self.assertIn('quality/snapshot_month={snapshot_month}/results.json', source)
        self.assertNotIn(
            'quality/snapshot_month={snapshot_month}/release_id=', source
        )
        self.assertIn('staging/commit-candidates/run_id=', source)

    def test_uncommitted_partial_output_is_recoverable(self):
        source = JOB_PATH.read_text(encoding="utf-8")
        self.assertIn("invisible to Gold until the commit marker exists", source)
        self.assertIn("_delete_prefix", source)


if __name__ == "__main__":
    unittest.main()
