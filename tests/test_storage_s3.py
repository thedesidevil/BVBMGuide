import json

import boto3
import pytest
from moto import mock_aws

from src.library.ui.storage import S3StorageBackend


@pytest.fixture
def s3_backend():
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        bucket = "test-bucket"
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        s3.put_object(Bucket=bucket, Key="db/existing.json", Body=json.dumps({"a": 1}))
        s3.put_object(Bucket=bucket, Key="db/binary.bin", Body=b"\x00\x01")
        s3.put_object(Bucket=bucket, Key="db/sub/nested.json", Body=json.dumps({"nested": True}))

        backend = S3StorageBackend(bucket=bucket, prefix="db")
        yield backend


class TestS3StorageBackend:
    def test_read_json_existing(self, s3_backend):
        assert s3_backend.read_json("existing.json") == {"a": 1}

    def test_read_json_missing(self, s3_backend):
        assert s3_backend.read_json("missing.json") is None

    def test_write_json(self, s3_backend):
        s3_backend.write_json("new.json", {"b": 2})
        assert s3_backend.read_json("new.json") == {"b": 2}

    def test_write_json_nested(self, s3_backend):
        s3_backend.write_json("deep/path/file.json", {"deep": True})
        assert s3_backend.read_json("deep/path/file.json") == {"deep": True}

    def test_read_bytes(self, s3_backend):
        assert s3_backend.read_bytes("binary.bin") == b"\x00\x01"

    def test_read_bytes_missing(self, s3_backend):
        assert s3_backend.read_bytes("nope.bin") is None

    def test_write_bytes(self, s3_backend):
        s3_backend.write_bytes("out.bin", b"data")
        assert s3_backend.read_bytes("out.bin") == b"data"

    def test_delete(self, s3_backend):
        s3_backend.delete("existing.json")
        assert s3_backend.read_json("existing.json") is None

    def test_delete_missing_no_error(self, s3_backend):
        s3_backend.delete("nonexistent.json")  # should not raise

    def test_list_keys(self, s3_backend):
        keys = sorted(s3_backend.list_keys(""))
        assert keys == ["binary.bin", "existing.json", "sub/nested.json"]

    def test_list_keys_with_prefix(self, s3_backend):
        keys = s3_backend.list_keys("sub/")
        assert keys == ["sub/nested.json"]

    def test_exists(self, s3_backend):
        assert s3_backend.exists("existing.json") is True
        assert s3_backend.exists("nope.json") is False

    def test_generate_presigned_put(self, s3_backend):
        url = s3_backend.generate_presigned_put("uploads/file.pdf", content_type="application/pdf")
        assert "test-bucket" in url
        assert "uploads" in url

    def test_delete_prefix(self, s3_backend):
        s3_backend.write_json("staging/session1/meta.json", {"id": "1"})
        s3_backend.write_bytes("staging/session1/file.pdf", b"pdf")
        s3_backend.delete_prefix("staging/session1/")
        assert s3_backend.list_keys("staging/session1/") == []
