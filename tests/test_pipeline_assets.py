import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PipelineAssetTests(unittest.TestCase):
    def test_glue_job_and_ruleset_are_executable_assets(self):
        script = (ROOT / "Glue" / "jobs" / "process_migration.py").read_text(
            encoding="utf-8"
        )
        rules = (
            ROOT / "Glue" / "rulesets" / "migration_arrivals.dqdl"
        ).read_text(encoding="utf-8")

        self.assertIn("job.commit()", script)
        self.assertIn("EvaluateDataQuality.apply", script)
        self.assertIn("snapshot_month", script)
        self.assertIn("Rules = [", rules)
        self.assertIn('ColumnValues "status" in ["Final", "Provisional"]', rules)

    def test_gold_views_are_versioned_and_slice_safe(self):
        terraform = (
            ROOT / "infrastructure" / "terraform" / "gold_views.tf"
        ).read_text(encoding="utf-8")
        self.assertIn("vw_latest_monthly_arrivals", terraform)
        self.assertIn("vw_total_arrivals", terraform)
        self.assertIn("vw_arrivals_by_citizenship", terraform)
        self.assertIn("vw_arrivals_by_visa", terraform)
        self.assertIn("metric_slice = 'total'", terraform)
        self.assertIn("metric_slice = 'citizenship'", terraform)
        self.assertIn("metric_slice = 'visa'", terraform)
        self.assertNotIn("SUM(estimate) AS arrivals", terraform)

    def test_runtime_is_aws_native_and_upload_driven(self):
        orchestration = (
            ROOT / "infrastructure" / "terraform" / "orchestration.tf"
        ).read_text(encoding="utf-8")
        self.assertIn("aws_s3_bucket_notification", orchestration)
        self.assertIn("aws_pipes_pipe", orchestration)
        self.assertIn("glue:startJobRun.sync", orchestration)
        self.assertNotIn("aws_lambda_function", orchestration)
        self.assertNotIn("aws_scheduler_schedule", orchestration)


if __name__ == "__main__":
    unittest.main()
