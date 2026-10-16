import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nz_migration_pipeline.contracts import (  # noqa: E402
    canonicalize_source_row,
    derive_metric_slice,
    revision_key,
)

FIXTURES = ROOT / "tests" / "fixtures"


def load_snapshot(index):
    releases = json.loads((FIXTURES / "releases.json").read_text())["fixtures"]
    release = releases[index]
    with (FIXTURES / release["fixture"]).open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return [
            canonicalize_source_row(
                row,
                snapshot_month=release["snapshot_month"],
                release_id=release["release_id"],
                source_sha256=release["source_sha256"],
                ingested_at="2026-10-16T10:00:00Z",
            )
            for row in rows
        ]


class MetricGrainTests(unittest.TestCase):
    def test_all_eight_cube_slices_are_classified(self):
        expected = {
            ("TOTAL", "TOTAL", "TOTAL"): "total",
            ("NZ", "TOTAL", "TOTAL"): "citizenship",
            ("TOTAL", "Work", "TOTAL"): "visa",
            ("TOTAL", "TOTAL", "India"): "country_of_residence",
            ("NZ", "Work", "TOTAL"): "citizenship_visa",
            ("NZ", "TOTAL", "India"): "citizenship_country_of_residence",
            ("TOTAL", "Work", "India"): "visa_country_of_residence",
            ("NZ", "Work", "India"): "citizenship_visa_country_of_residence",
        }
        for dimensions, metric_slice in expected.items():
            record = dict(
                zip(("citizenship", "visa", "country_of_residence"), dimensions)
            )
            self.assertEqual(metric_slice, derive_metric_slice(record))

    def test_kpi_uses_only_the_triple_total_slice(self):
        records = load_snapshot(0)
        total_rows = [record for record in records if record["metric_slice"] == "total"]
        self.assertEqual(1, len(total_rows))
        self.assertEqual(10600, sum(record["estimate"] for record in total_rows))
        self.assertNotEqual(10600, sum(record["estimate"] for record in records))

    def test_revision_key_matches_the_same_fact_across_snapshots(self):
        october = {revision_key(record): record for record in load_snapshot(0)}
        november = {revision_key(record): record for record in load_snapshot(1)}
        self.assertEqual(set(october), set(november))

        total_key = next(
            key for key, record in october.items() if record["metric_slice"] == "total"
        )
        self.assertEqual(
            -146, november[total_key]["estimate"] - october[total_key]["estimate"]
        )
        self.assertEqual("2025-10", october[total_key]["snapshot_month"])
        self.assertEqual("2025-11", november[total_key]["snapshot_month"])


if __name__ == "__main__":
    unittest.main()
