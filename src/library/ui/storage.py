"""Storage abstraction for library database — filesystem and S3 backends."""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class StorageBackend(ABC):
    """Unified storage interface for local filesystem and S3."""

    @abstractmethod
    def read_json(self, key: str) -> Optional[dict]:
        """Read and parse a JSON file. Returns None if not found."""

    @abstractmethod
    def write_json(self, key: str, data: dict) -> None:
        """Serialize and write a JSON file."""

    @abstractmethod
    def read_bytes(self, key: str) -> Optional[bytes]:
        """Read raw bytes. Returns None if not found."""

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> None:
        """Write raw bytes."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a file/object. No error if missing."""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """List all keys under a prefix (recursive)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""

    def generate_presigned_put(self, key: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> Optional[str]:
        """Generate a presigned PUT URL. Returns None if not supported (local backend)."""
        return None


class LocalStorageBackend(StorageBackend):
    """Filesystem-backed storage. Keys are relative paths from base_path."""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def _resolve(self, key: str) -> Path:
        return self.base_path / key

    def read_json(self, key: str) -> Optional[dict]:
        path = self._resolve(key)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, key: str, data: dict) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def read_bytes(self, key: str) -> Optional[bytes]:
        path = self._resolve(key)
        if not path.exists():
            return None
        return path.read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def list_keys(self, prefix: str) -> list[str]:
        search_path = self._resolve(prefix) if prefix else self.base_path
        if not search_path.exists():
            return []
        keys = []
        for path in search_path.rglob("*"):
            if path.is_file():
                keys.append(str(path.relative_to(self.base_path)))
        return keys

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()


class S3StorageBackend(StorageBackend):
    """S3-backed storage. Keys are relative to a prefix within a bucket."""

    def __init__(self, bucket: str, prefix: str = ""):
        import boto3

        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        self._s3 = boto3.client("s3")

    def _full_key(self, key: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def read_json(self, key: str) -> Optional[dict]:
        data = self.read_bytes(key)
        if data is None:
            return None
        return json.loads(data.decode("utf-8"))

    def write_json(self, key: str, data: dict) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.write_bytes(key, body)

    def read_bytes(self, key: str) -> Optional[bytes]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=self._full_key(key))
            return resp["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None

    def write_bytes(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self._full_key(key), Body=data)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._full_key(key))

    def list_keys(self, prefix: str) -> list[str]:
        full_prefix = self._full_key(prefix) if prefix else (self.prefix + "/" if self.prefix else "")
        keys = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                rel_key = obj["Key"]
                if self.prefix:
                    rel_key = rel_key[len(self.prefix) + 1:]
                keys.append(rel_key)
        return keys

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._full_key(key))
            return True
        except self._s3.exceptions.ClientError:
            return False

    def generate_presigned_put(self, key: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> Optional[str]:
        """Generate a presigned PUT URL for direct browser upload."""
        return self._s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._full_key(key),
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    def delete_prefix(self, prefix: str) -> None:
        """Delete all objects under a prefix (for session cleanup)."""
        keys = self.list_keys(prefix)
        for key in keys:
            self.delete(key)


def get_storage_backend() -> StorageBackend:
    """Select backend based on environment. S3 on Lambda, local filesystem otherwise."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        bucket = os.environ["LIBRARY_S3_BUCKET"]
        prefix = os.environ.get("LIBRARY_S3_PREFIX", "library_db")
        return S3StorageBackend(bucket=bucket, prefix=prefix)
    else:
        db_path = os.environ.get("LIBRARY_DB_PATH", "library_db")
        return LocalStorageBackend(Path(db_path))
