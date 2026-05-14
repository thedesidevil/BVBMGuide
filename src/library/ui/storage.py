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
