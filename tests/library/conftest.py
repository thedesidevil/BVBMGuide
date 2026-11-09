import json
from typing import Optional

import pytest

from src.library.ui.services.db_service import LibraryDBService
from src.library.ui.storage import StorageBackend


class MemoryBackend(StorageBackend):
    """Dict-backed storage. JSON round-trips so non-serialisable values fail."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.writes: list[str] = []

    def read_json(self, key: str) -> Optional[dict]:
        raw = self.files.get(key)
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def write_json(self, key: str, data: dict) -> None:
        self.write_bytes(key, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def read_bytes(self, key: str) -> Optional[bytes]:
        return self.files.get(key)

    def write_bytes(self, key: str, data: bytes) -> None:
        self.files[key] = bytes(data)
        self.writes.append(key)

    def delete(self, key: str) -> None:
        self.files.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return [k for k in self.files if k.startswith(prefix)]

    def exists(self, key: str) -> bool:
        return key in self.files


@pytest.fixture
def memory_backend():
    return MemoryBackend()


@pytest.fixture
def memory_db(memory_backend):
    return LibraryDBService(memory_backend)
