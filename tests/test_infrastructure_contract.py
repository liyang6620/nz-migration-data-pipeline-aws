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
            'resource "aws_glue_job"',
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
            "reserved_concurrent_executions = 1",
            "bytes_scanned_cutoff_per_query",
            "default     = false",
        )
        for guardrail in required:
            self.assertIn(guardrail, self.configuration)

    def test_budget_defaults_to_three_us_dollars(self):
        variables = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
        budget = variables.split('variable "monthly_budget_usd"', 1)[1]
        self.assertIn("default     = 3", budget)


if __name__ == "__main__":
    unittest.main()
