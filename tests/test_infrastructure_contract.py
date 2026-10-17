import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = ROOT / "infrastructure" / "terraform"


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configuration = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(TERRAFORM.glob("*.tf"))
        )

    def test_no_always_on_or_high_cost_services_are_declared(self):
        forbidden = (
            'resource "aws_nat_gateway"',
            'resource "aws_instance"',
            'resource "aws_ecs_service"',
            'resource "aws_lambda_function"',
            'resource "aws_ecr_repository"',
            'resource "aws_scheduler_schedule"',
            'resource "aws_mwaa_environment"',
            'resource "aws_quicksight_',
            'resource "aws_redshift_',
        )
        for resource in forbidden:
            self.assertNotIn(resource, self.configuration)

    def test_storage_and_compute_guardrails_are_declared(self):
        required = (
            "force_destroy = false",
            'status = "Enabled"',
            'sse_algorithm = "AES256"',
            "max_concurrent_runs = 1",
            "number_of_workers = var.glue_number_of_workers",
            "timeout           = var.glue_timeout_minutes",
            "bytes_scanned_cutoff_per_query",
            "content_based_deduplication = true",
            "deadLetterTargetArn",
            "point_in_time_recovery",
        )
        for guardrail in required:
            self.assertIn(guardrail, self.configuration)

    def test_uploads_drive_an_aws_native_control_plane(self):
        required = (
            'resource "aws_s3_bucket_notification"',
            'resource "aws_cloudwatch_event_rule" "landing_upload"',
            'resource "aws_sqs_queue" "uploads"',
            'resource "aws_pipes_pipe" "uploads"',
            'resource "aws_sfn_state_machine" "pipeline"',
            'resource "aws_glue_job" "pipeline"',
            'resource "aws_dynamodb_table" "pipeline_runs"',
        )
        for resource in required:
            self.assertIn(resource, self.configuration)

    def test_pipe_target_failures_are_logged(self):
        orchestration = (TERRAFORM / "orchestration.tf").read_text(encoding="utf-8")
        self.assertIn('resource "aws_cloudwatch_log_group" "pipes"', orchestration)
        self.assertIn('level                  = "ERROR"', orchestration)
        self.assertIn('include_execution_data = ["ALL"]', orchestration)

    def test_gold_views_only_expose_committed_snapshots(self):
        self.assertGreaterEqual(self.configuration.count("VIRTUAL_VIEW"), 1)
        self.assertIn("release_commits", self.configuration)
        self.assertIn("commits.status = 'SUCCEEDED'", self.configuration)
        for view in (
            "vw_latest_monthly_arrivals",
            "vw_total_arrivals",
            "vw_arrivals_by_citizenship",
            "vw_arrivals_by_visa",
            "vw_revision_summary",
            "vw_release_history",
            "vw_pipeline_quality",
        ):
            self.assertIn(view, self.configuration)

    def test_failed_runs_are_replayable_without_reprocessing_successes(self):
        orchestration = (TERRAFORM / "orchestration.tf").read_text(encoding="utf-8")
        self.assertIn("ReadExistingRun", orchestration)
        self.assertIn("ReopenRun", orchestration)
        self.assertIn('StringEquals = "FAILED"', orchestration)
        self.assertIn('StringEquals = "QUARANTINED"', orchestration)

    def test_hyphenated_event_fields_use_reference_path_brackets(self):
        orchestration = (TERRAFORM / "orchestration.tf").read_text(encoding="utf-8")
        self.assertIn("$.detail.object['version-id']", orchestration)
        self.assertNotIn("$.detail.object.version-id", orchestration)

    def test_budget_defaults_to_three_us_dollars(self):
        variables = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
        budget = variables.split('variable "monthly_budget_usd"', 1)[1]
        self.assertIn("default     = 3", budget)

    def test_lake_formation_is_bootstrapped_before_grants(self):
        governance = (TERRAFORM / "governance.tf").read_text(encoding="utf-8")
        self.assertIn(
            'resource "aws_lakeformation_data_lake_settings" "pipeline"',
            governance,
        )
        self.assertNotIn("create_database_default_permissions", governance)
        self.assertNotIn("create_table_default_permissions", governance)
        self.assertNotIn('principal   = "IAM_ALLOWED_PRINCIPALS"', governance)
        self.assertIn(
            "depends_on = [aws_lakeformation_data_lake_settings.pipeline]",
            governance,
        )


if __name__ == "__main__":
    unittest.main()
