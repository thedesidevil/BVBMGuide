import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def local_db(tmp_path):
    """Create a minimal library_db directory with test data."""
    index = {
        "_folder_coverage": {"italy": ["Rome", "Florence"]},
        "_review_status": {},
        "_processed_files": {},
    }
    (tmp_path / "_index.json").write_text(json.dumps(index))
    (tmp_path / "Rome.json").write_text(json.dumps({
        "restaurants": [{"name": "Trattoria Roma", "city": "Rome"}],
        "attractions": [],
        "hotels": [],
    }))
    (tmp_path / "Florence.json").write_text(json.dumps({
        "restaurants": [],
        "attractions": [{"name": "Uffizi Gallery", "city": "Florence"}],
        "hotels": [],
    }))
    (tmp_path / "_country").mkdir()
    (tmp_path / "_country" / "Italy.json").write_text(json.dumps({
        "safety_tips": [{"tip": "Watch for pickpockets"}],
    }))
    return tmp_path


@pytest.fixture
def s3_bucket():
    """Create a mocked S3 bucket with test data."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        bucket = "test-library"
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )

        prefix = "library_db"
        index = {
            "_folder_coverage": {"italy": ["Rome", "Florence"]},
            "_review_status": {},
            "_processed_files": {},
        }
        s3.put_object(Bucket=bucket, Key=f"{prefix}/_index.json", Body=json.dumps(index))
        s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}/Rome.json",
            Body=json.dumps({
                "restaurants": [{"name": "Trattoria Roma", "city": "Rome"}],
                "attractions": [],
                "hotels": [],
            }),
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}/Florence.json",
            Body=json.dumps({
                "restaurants": [],
                "attractions": [{"name": "Uffizi Gallery", "city": "Florence"}],
                "hotels": [],
            }),
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}/_country/Italy.json",
            Body=json.dumps({"safety_tips": [{"tip": "Watch for pickpockets"}]}),
        )

        yield {"bucket": bucket, "prefix": prefix, "client": s3}
