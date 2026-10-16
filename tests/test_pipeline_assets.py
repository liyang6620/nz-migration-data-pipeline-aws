import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PipelineAssetTests(unittest.TestCase):
    def test_state_machine_references_existing_states(self):
        definition = json.loads(
            (ROOT / "Stepfunction" / "nz_immigration_statemachine.asl.json").read_text()
        )
        states = definition["States"]
        self.assertIn(definition["StartAt"], states)

        for state in states.values():
            next_state = state.get("Next")
            if next_state:
                self.assertIn(next_state, states)

    def test_glue_export_contains_executable_script(self):
        job = json.loads(
            (ROOT / "Glue" / "nz_migration_arrivals_curated_job.json").read_text()
        )
        script = job.get("script", "")
        self.assertIn("job.commit()", script)
        self.assertIn("snapshot_month", script)

    def test_reporting_views_are_versioned(self):
        sql = (ROOT / "Athena" / "views.sql").read_text(encoding="utf-8")
        self.assertGreaterEqual(sql.upper().count("CREATE OR REPLACE VIEW"), 3)

    def test_reporting_views_select_one_cube_slice_without_resumming(self):
        sql = (ROOT / "Athena" / "views.sql").read_text(encoding="utf-8")
        self.assertIn("metric_slice = 'total'", sql)
        self.assertIn("metric_slice = 'country_of_residence'", sql)
        self.assertIn("metric_slice = 'visa'", sql)
        self.assertNotIn("SUM(estimate)", sql)


if __name__ == "__main__":
    unittest.main()
