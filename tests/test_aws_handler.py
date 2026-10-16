import hashlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

from nz_migration_pipeline import aws_handler  # noqa: E402
from nz_migration_pipeline.contracts import ContractViolation  # noqa: E402
from nz_migration_pipeline.ingest import AcquiredSource  # noqa: E402


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def head_object(self, *, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "missing"}},
                "HeadObject",
            )
        return {"Metadata": self.objects[Key].get("metadata", {})}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        del Bucket
        self.objects[Key] = {
            "body": Body if isinstance(Body, bytes) else Body.read(),
            "metadata": kwargs.get("Metadata", {}),
        }


class AwsIngestHandlerTests(unittest.TestCase):
    def setUp(self):
        self.fake_s3 = FakeS3()
        aws_handler.S3 = self.fake_s3
        self.previous_bucket = os.environ.get("DATA_BUCKET")
        os.environ["DATA_BUCKET"] = "test-bucket"

    def tearDown(self):
        aws_handler.S3 = None
        if self.previous_bucket is None:
            os.environ.pop("DATA_BUCKET", None)
        else:
            os.environ["DATA_BUCKET"] = self.previous_bucket

    def test_ingest_commits_manifest_last_and_is_idempotent(self):
        content = b"header\nvalue\n"
        digest = hashlib.sha256(content).hexdigest()
        acquired = AcquiredSource(
            content=content,
            source_uri="https://example.test/release.csv",
            sha256=digest,
        )
        event = {
            "source_url": acquired.source_uri,
            "release_id": "release-2025-10",
            "snapshot_month": "2025-10",
            "expected_sha256": digest,
        }
        with patch.object(aws_handler, "acquire_source", return_value=acquired):
            first = aws_handler.ingest_handler(event, None)
            second = aws_handler.ingest_handler(event, None)

        self.assertEqual("processed", first["ingest_status"])
        self.assertEqual("skipped", second["ingest_status"])
        manifest_key = "raw/release_id=release-2025-10/manifest.json"
        manifest = json.loads(self.fake_s3.objects[manifest_key]["body"])
        self.assertEqual(digest, manifest["source_sha256"])
        self.assertIn("raw/release_id=release-2025-10/source.csv", self.fake_s3.objects)

    def test_ingest_rejects_changed_content_for_same_release(self):
        original = b"original"
        changed = b"changed"
        event = {
            "source_url": "https://example.test/release.csv",
            "release_id": "release-2025-10",
            "snapshot_month": "2025-10",
        }
        with patch.object(
            aws_handler,
            "acquire_source",
            return_value=AcquiredSource(
                original,
                event["source_url"],
                hashlib.sha256(original).hexdigest(),
            ),
        ):
            aws_handler.ingest_handler(event, None)
        with patch.object(
            aws_handler,
            "acquire_source",
            return_value=AcquiredSource(
                changed,
                event["source_url"],
                hashlib.sha256(changed).hexdigest(),
            ),
        ):
            with self.assertRaisesRegex(ContractViolation, "different content"):
                aws_handler.ingest_handler(event, None)

    def test_event_requires_an_https_source_and_release_fields(self):
        with self.assertRaisesRegex(ContractViolation, "HTTP"):
            aws_handler._required_event(
                {
                    "source_url": "file:///tmp/source.csv",
                    "release_id": "release-2025-10",
                    "snapshot_month": "2025-10",
                }
            )
        with self.assertRaisesRegex(ContractViolation, "missing event field"):
            aws_handler._required_event({})


if __name__ == "__main__":
    unittest.main()
