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
    CANONICAL_COLUMNS,
    ContractViolation,
    canonicalize_source_row,
    record_key,
)


FIXTURES = ROOT / "tests" / "fixtures"
INGESTED_AT = "2026-10-16T10:00:00Z"


def read_rows(name):
    with (FIXTURES / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def canonicalize(rows, snapshot_month, release_id, source_sha256):
    return [
        canonicalize_source_row(
            row,
            snapshot_month=snapshot_month,
            release_id=release_id,
            source_sha256=source_sha256,
            ingested_at=INGESTED_AT,
        )
        for row in rows
    ]


class DataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.releases = json.loads((FIXTURES / "releases.json").read_text())[
            "fixtures"
        ]

    def test_real_source_fixtures_satisfy_contract(self):
        for release in self.releases:
            records = canonicalize(
                read_rows(release["fixture"]),
                release["snapshot_month"],
                release["release_id"],
                release["source_sha256"],
            )
            self.assertEqual(5, len(records))
            self.assertEqual(set(CANONICAL_COLUMNS), set(records[0]))
            self.assertIsInstance(records[0]["estimate"], int)
            self.assertIsInstance(records[0]["standard_error"], float)

    def test_duplicate_business_key_is_detectable(self):
        release = self.releases[0]
        records = canonicalize(
            read_rows("invalid_duplicate.csv"),
            release["snapshot_month"],
            release["release_id"],
            release["source_sha256"],
        )
        keys = [record_key(record) for record in records]
        self.assertNotEqual(len(keys), len(set(keys)))

    def test_negative_estimate_is_rejected(self):
        row = read_rows(self.releases[0]["fixture"])[0]
        row["estimate"] = "-1"
        with self.assertRaisesRegex(ContractViolation, "non-negative"):
            canonicalize_source_row(
                row,
                snapshot_month="2025-10",
                release_id="test-release",
                source_sha256="0" * 64,
                ingested_at=INGESTED_AT,
            )

    def test_non_finite_standard_error_is_rejected(self):
        row = read_rows(self.releases[0]["fixture"])[0]
        row["standard_error"] = "NaN"
        with self.assertRaisesRegex(ContractViolation, "finite"):
            canonicalize_source_row(
                row,
                snapshot_month="2025-10",
                release_id="test-release",
                source_sha256="0" * 64,
                ingested_at=INGESTED_AT,
            )

    def test_unexpected_source_column_is_rejected(self):
        row = read_rows(self.releases[0]["fixture"])[0]
        row["unannounced_column"] = "value"
        with self.assertRaisesRegex(ContractViolation, "unexpected columns"):
            canonicalize_source_row(
                row,
                snapshot_month="2025-10",
                release_id="test-release",
                source_sha256="0" * 64,
                ingested_at=INGESTED_AT,
            )

    def test_future_source_release_is_rejected(self):
        row = read_rows(self.releases[0]["fixture"])[0]
        row["month_of_release"] = "2025-11"
        with self.assertRaisesRegex(ContractViolation, "after snapshot_month"):
            canonicalize_source_row(
                row,
                snapshot_month="2025-10",
                release_id="test-release",
                source_sha256="0" * 64,
                ingested_at=INGESTED_AT,
            )

    def test_departures_are_outside_current_source_scope(self):
        row = read_rows(self.releases[0]["fixture"])[0]
        row["direction"] = "Departures"
        with self.assertRaisesRegex(ContractViolation, "only supports Arrivals"):
            canonicalize_source_row(
                row,
                snapshot_month="2025-10",
                release_id="test-release",
                source_sha256="0" * 64,
                ingested_at=INGESTED_AT,
            )

    def test_json_schema_and_python_contract_require_same_fields(self):
        schema = json.loads(
            (ROOT / "contracts" / "canonical_fact.schema.json").read_text()
        )
        self.assertEqual(set(CANONICAL_COLUMNS), set(schema["required"]))


if __name__ == "__main__":
    unittest.main()
