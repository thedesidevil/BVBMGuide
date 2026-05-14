# AWSify Library QC UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Library QC UI to AWS Lambda with S3-backed storage, keeping local dev workflow unchanged.

**Architecture:** Storage abstraction layer (`StorageBackend`) with two implementations — `LocalStorageBackend` (filesystem, for local dev) and `S3StorageBackend` (boto3, for Lambda). Services are refactored to depend on the interface. Mangum wraps the FastAPI app for Lambda. Frontend gains presigned-URL upload for the ingest wizard.

**Tech Stack:** Python 3.14, FastAPI, Mangum, boto3, pytest + moto (tests), Vite/React/TypeScript (frontend)

---

## File Structure

```
src/library/ui/
├── storage.py              — StorageBackend ABC + LocalStorageBackend + S3StorageBackend + factory
├── lambda_handler.py       — Mangum entry point for Lambda
├── __init__.py             — (modify) create_app() accepts optional storage_backend
├── server.py              — (no changes)
├── services/
│   ├── db_service.py      — (modify) accept StorageBackend instead of Path
│   ├── audit_service.py   — (modify) accept StorageBackend instead of Path
│   ├── ingest_service.py  — (modify) accept StorageBackend, presigned URL generation
│   └── country_extractor.py — (modify) accept StorageBackend instead of Path
└── api/
    ├── tree.py            — (modify) get service from app.state.storage_backend
    ├── city.py            — (modify) same
    ├── country.py         — (modify) same
    ├── review.py          — (modify) same
    ├── sweep.py           — (modify) same
    ├── audit.py           — (modify) same
    └── ingest.py          — (modify) presigned upload endpoints + use storage_backend

ui-frontend/src/api/
└── client.ts              — (modify) presigned upload flow

tests/
├── conftest.py            — pytest fixtures (tmp_path backend, moto S3)
├── test_storage.py        — StorageBackend interface tests
├── test_db_service.py     — LibraryDBService with backend
└── test_ingest_service.py — IngestService with backend

deploy/aws/
├── sam-template.yaml
├── build-deploy-lambda.sh
├── lambda-requirements.txt
└── QUICKSTART.md
```

---

### Task 1: Set Up Test Infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pyproject.toml` (pytest config section only)

- [ ] **Step 1: Install test dependencies**

```bash
pip install pytest moto[s3] boto3
```

- [ ] **Step 2: Create pyproject.toml with pytest config**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Create tests/__init__.py**

Empty file.

- [ ] **Step 4: Create tests/conftest.py with shared fixtures**

```python
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
```

- [ ] **Step 5: Verify pytest discovers the fixtures**

Run: `pytest --co -q`
Expected: "no tests ran" (no test files yet), no errors

- [ ] **Step 6: Commit**

```bash
git add tests/ pyproject.toml
git commit -m "chore: set up pytest + moto test infrastructure"
```

---

### Task 2: StorageBackend Interface + LocalStorageBackend

**Files:**
- Create: `src/library/ui/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for LocalStorageBackend**

```python
import json
from pathlib import Path

import pytest

from src.library.ui.storage import LocalStorageBackend


class TestLocalStorageBackend:
    def test_read_json_existing(self, tmp_path):
        (tmp_path / "test.json").write_text(json.dumps({"key": "value"}))
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_json("test.json") == {"key": "value"}

    def test_read_json_missing(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_json("missing.json") is None

    def test_write_json(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_json("out.json", {"hello": "world"})
        assert json.loads((tmp_path / "out.json").read_text()) == {"hello": "world"}

    def test_write_json_nested(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_json("sub/dir/out.json", {"nested": True})
        assert (tmp_path / "sub" / "dir" / "out.json").exists()

    def test_read_bytes(self, tmp_path):
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_bytes("binary.bin") == b"\x00\x01\x02"

    def test_read_bytes_missing(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_bytes("nope.bin") is None

    def test_write_bytes(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_bytes("data.bin", b"hello")
        assert (tmp_path / "data.bin").read_bytes() == b"hello"

    def test_delete(self, tmp_path):
        (tmp_path / "doomed.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        backend.delete("doomed.json")
        assert not (tmp_path / "doomed.json").exists()

    def test_delete_missing_no_error(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.delete("nonexistent.json")  # should not raise

    def test_list_keys(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        keys = sorted(backend.list_keys(""))
        assert keys == ["a.json", "b.json", "sub/c.json"]

    def test_list_keys_with_prefix(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "one.json").write_text("{}")
        (tmp_path / "sub" / "two.json").write_text("{}")
        (tmp_path / "other.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        keys = sorted(backend.list_keys("sub/"))
        assert keys == ["sub/one.json", "sub/two.json"]

    def test_exists(self, tmp_path):
        (tmp_path / "yes.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        assert backend.exists("yes.json") is True
        assert backend.exists("no.json") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v`
Expected: ImportError — `storage` module doesn't exist yet

- [ ] **Step 3: Implement StorageBackend ABC + LocalStorageBackend**

Create `src/library/ui/storage.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/storage.py tests/test_storage.py
git commit -m "feat(storage): add StorageBackend ABC and LocalStorageBackend"
```

---

### Task 3: S3StorageBackend

**Files:**
- Modify: `src/library/ui/storage.py`
- Create: `tests/test_storage_s3.py`

- [ ] **Step 1: Write failing tests for S3StorageBackend**

Create `tests/test_storage_s3.py`:

```python
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
        assert "uploads/file.pdf" in url or "uploads%2Ffile.pdf" in url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage_s3.py -v`
Expected: ImportError — `S3StorageBackend` not defined yet

- [ ] **Step 3: Implement S3StorageBackend**

Add to `src/library/ui/storage.py`:

```python
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

    def generate_presigned_put(self, key: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> str:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage_s3.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Add factory function to storage.py**

Append to `src/library/ui/storage.py`:

```python
def get_storage_backend() -> StorageBackend:
    """Select backend based on environment. S3 on Lambda, local filesystem otherwise."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        bucket = os.environ["LIBRARY_S3_BUCKET"]
        prefix = os.environ.get("LIBRARY_S3_PREFIX", "library_db")
        return S3StorageBackend(bucket=bucket, prefix=prefix)
    else:
        db_path = os.environ.get("LIBRARY_DB_PATH", "library_db")
        return LocalStorageBackend(Path(db_path))
```

- [ ] **Step 6: Commit**

```bash
git add src/library/ui/storage.py tests/test_storage_s3.py
git commit -m "feat(storage): add S3StorageBackend with presigned URL support"
```

---

### Task 4: Refactor LibraryDBService to Use StorageBackend

**Files:**
- Modify: `src/library/ui/services/db_service.py`
- Create: `tests/test_db_service.py`

- [ ] **Step 1: Write tests for LibraryDBService with StorageBackend**

Create `tests/test_db_service.py`:

```python
import json
from pathlib import Path

import pytest

from src.library.ui.services.db_service import LibraryDBService
from src.library.ui.storage import LocalStorageBackend


@pytest.fixture
def db_service(local_db):
    backend = LocalStorageBackend(local_db)
    return LibraryDBService(backend)


class TestLibraryDBService:
    def test_get_folder_coverage(self, db_service):
        coverage = db_service.get_folder_coverage()
        assert "italy" in coverage
        assert "Rome" in coverage["italy"]

    def test_get_city_data(self, db_service):
        data = db_service.get_city_data("Rome")
        assert data is not None
        assert data["restaurants"][0]["name"] == "Trattoria Roma"

    def test_get_city_data_missing(self, db_service):
        assert db_service.get_city_data("Atlantis") is None

    def test_save_city_data(self, db_service):
        db_service.save_city_data("Rome", {"restaurants": [], "attractions": []})
        data = db_service.get_city_data("Rome")
        assert data["restaurants"] == []

    def test_get_country_data(self, db_service):
        data = db_service.get_country_data("Italy")
        assert data is not None
        assert data["safety_tips"][0]["tip"] == "Watch for pickpockets"

    def test_save_country_data(self, db_service):
        db_service.save_country_data("Italy", {"safety_tips": []})
        data = db_service.get_country_data("Italy")
        assert data["safety_tips"] == []

    def test_get_all_city_names(self, db_service):
        names = db_service.get_all_city_names()
        assert "Rome" in names
        assert "Florence" in names
        assert "_index" not in names

    def test_set_review_status(self, db_service):
        db_service.set_review_status("Rome", "reviewed", "marina")
        status = db_service.get_review_status()
        assert status["Rome"]["status"] == "reviewed"
        assert status["Rome"]["reviewed_by"] == "marina"

    def test_get_tree(self, db_service):
        tree = db_service.get_tree()
        assert "italy" in tree
        city_names = [c["name"] for c in tree["italy"]["cities"]]
        assert "Rome" in city_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db_service.py -v`
Expected: TypeError — `LibraryDBService.__init__()` expects `db_path`, not a `StorageBackend`

- [ ] **Step 3: Rewrite LibraryDBService to use StorageBackend**

Replace `src/library/ui/services/db_service.py`:

```python
import json
from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend


class LibraryDBService:
    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._index: dict = {}
        self._load_index()

    def _load_index(self):
        data = self.backend.read_json("_index.json")
        self._index = data if data else {}

    def _save_index(self):
        self.backend.write_json("_index.json", self._index)

    def get_folder_coverage(self) -> dict[str, list[str]]:
        return self._index.get("_folder_coverage", {})

    def get_review_status(self) -> dict[str, dict]:
        return self._index.get("_review_status", {})

    def set_review_status(self, name: str, status: str, reviewed_by: str = "unknown"):
        if "_review_status" not in self._index:
            self._index["_review_status"] = {}
        now = datetime.now(timezone.utc).isoformat()
        if status == "reviewed":
            self._index["_review_status"][name] = {
                "status": "reviewed",
                "reviewed_at": now,
                "reviewed_by": reviewed_by,
            }
        elif status == "in_progress":
            self._index["_review_status"][name] = {
                "status": "in_progress",
                "last_edited": now,
            }
        else:
            self._index["_review_status"][name] = {"status": "pending"}
        self._save_index()

    def get_city_data(self, city: str) -> Optional[dict]:
        return self.backend.read_json(f"{city}.json")

    def save_city_data(self, city: str, data: dict):
        self.backend.write_json(f"{city}.json", data)

    def get_country_data(self, country: str) -> Optional[dict]:
        return self.backend.read_json(f"_country/{country}.json")

    def save_country_data(self, country: str, data: dict):
        self.backend.write_json(f"_country/{country}.json", data)

    def get_all_city_names(self) -> list[str]:
        all_keys = self.backend.list_keys("")
        names = []
        for key in sorted(all_keys):
            if "/" in key:
                continue
            if key.endswith(".json") and key not in ("_index.json", "_audit.json"):
                names.append(key[:-5])
        return names

    def get_tree(self) -> dict:
        coverage = self.get_folder_coverage()
        review_status = self.get_review_status()
        existing_shards = set(self.get_all_city_names())

        tree = {}
        for folder, cities in sorted(coverage.items()):
            city_nodes = []
            for city in sorted(cities):
                if city in existing_shards:
                    shard = self.get_city_data(city)
                    restaurant_count = len(shard.get("restaurants", [])) if shard else 0
                    city_nodes.append({
                        "name": city,
                        "status": review_status.get(city, {}).get("status", "pending"),
                        "restaurant_count": restaurant_count,
                    })
            tree[folder] = {
                "cities": city_nodes,
                "status": review_status.get(folder, {}).get("status", "pending"),
            }

        return tree
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db_service.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/services/db_service.py tests/test_db_service.py
git commit -m "refactor(db-service): use StorageBackend instead of filesystem Path"
```

---

### Task 5: Refactor AuditService to Use StorageBackend

**Files:**
- Modify: `src/library/ui/services/audit_service.py`

- [ ] **Step 1: Rewrite AuditService to use StorageBackend**

Replace `src/library/ui/services/audit_service.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend


class AuditService:
    """Manages the deletion audit trail at _audit.json."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        data = self.backend.read_json("_audit.json")
        self._entries = data if isinstance(data, list) else []

    def _save(self):
        self.backend.write_json("_audit.json", self._entries)

    def log_deletion(
        self,
        category: str,
        city: str,
        item_name: str,
        reason: str,
        item_snapshot: dict,
        deleted_by: str = "unknown",
    ):
        entry = {
            "action": "delete",
            "category": category,
            "city": city,
            "item_name": item_name,
            "reason": reason,
            "deleted_by": deleted_by,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "item_snapshot": item_snapshot,
        }
        self._entries.append(entry)
        self._save()

    def get_entries(self, limit: Optional[int] = None) -> list[dict]:
        entries = list(reversed(self._entries))
        if limit:
            return entries[:limit]
        return entries
```

- [ ] **Step 2: Verify existing tests still pass (if any reference audit)**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/library/ui/services/audit_service.py
git commit -m "refactor(audit-service): use StorageBackend instead of filesystem Path"
```

---

### Task 6: Refactor IngestSession and IngestService

**Files:**
- Modify: `src/library/ui/services/ingest_service.py`

This is the largest refactor. `IngestSession` switches from filesystem paths to `StorageBackend` for meta and upload storage. The key insight: on Lambda, staging lives at `_staging/{session_id}/` within the same S3 backend.

- [ ] **Step 1: Rewrite IngestSession to use StorageBackend**

Replace the `IngestSession` class (lines 14-117) in `src/library/ui/services/ingest_service.py`:

```python
class IngestSession:
    """Manages one ingest session's staging data via StorageBackend."""

    def __init__(self, session_id: str, backend: 'StorageBackend'):
        self.session_id = session_id
        self.backend = backend
        self._prefix = f"_staging/{session_id}"

    def _key(self, subpath: str) -> str:
        return f"{self._prefix}/{subpath}"

    def load_meta(self) -> dict:
        data = self.backend.read_json(self._key("meta.json"))
        if data:
            return data
        return {
            "session_id": self.session_id,
            "created_at": "",
            "files": {},
        }

    def save_meta(self, meta: dict):
        self.backend.write_json(self._key("meta.json"), meta)

    def add_file(self, file_id: str, filename: str, size: int, file_type: str) -> dict:
        meta = self.load_meta()
        entry = {
            "file_id": file_id,
            "filename": filename,
            "size": size,
            "type": file_type,
            "state": "uploaded",
        }
        meta["files"][file_id] = entry
        self.save_meta(meta)
        return entry

    def remove_file(self, file_id: str):
        meta = self.load_meta()
        entry = meta["files"].pop(file_id, None)
        self.save_meta(meta)
        if entry:
            self.backend.delete(self._upload_key(file_id, entry))
        self.backend.delete(self._key(f"extracted/{file_id}.json"))

    def get_files(self) -> dict:
        return self.load_meta().get("files", {})

    def get_file(self, file_id: str) -> Optional[dict]:
        return self.get_files().get(file_id)

    def update_file(self, file_id: str, updates: dict):
        meta = self.load_meta()
        if file_id in meta["files"]:
            meta["files"][file_id].update(updates)
            self.save_meta(meta)

    def get_upload_key(self, file_id: str) -> str:
        """Return the storage key for an uploaded file."""
        entry = self.get_file(file_id)
        ext = self._ext(entry) if entry else ""
        return self._key(f"uploads/{file_id}{ext}")

    def get_extracted_key(self, file_id: str) -> str:
        """Return the storage key for extracted JSON."""
        return self._key(f"extracted/{file_id}.json")

    def cleanup(self):
        """Remove all staging data for this session."""
        if hasattr(self.backend, "delete_prefix"):
            self.backend.delete_prefix(self._prefix + "/")
        else:
            keys = self.backend.list_keys(self._prefix + "/")
            for key in keys:
                self.backend.delete(key)

    def _upload_key(self, file_id: str, entry: dict) -> str:
        return self._key(f"uploads/{file_id}{self._ext(entry)}")

    def _ext(self, entry: dict) -> str:
        file_type = entry.get("type", "") if entry else ""
        if not file_type:
            return ""
        if not file_type.startswith("."):
            return f".{file_type}"
        return file_type
```

- [ ] **Step 2: Rewrite IngestService to use StorageBackend**

Replace the `IngestService` class (lines 120+) in `src/library/ui/services/ingest_service.py`:

```python
class IngestService:
    """Orchestrates upload, classify, extract, and persist for the ingest wizard."""

    _CITY_FIELDS = {"restaurants", "attractions", "hotels", "local_dishes", "souvenirs"}
    _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips", "phrases",
                          "emergency_contacts", "transport_options"}

    def __init__(self, backend: 'StorageBackend', library_path: Optional[Path] = None):
        self.backend = backend
        self.library_path = library_path

    def create_session(self) -> IngestSession:
        session_id = str(uuid.uuid4())
        session = IngestSession(session_id, self.backend)
        meta = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        session.save_meta(meta)
        return session

    def get_session(self, session_id: str) -> Optional[IngestSession]:
        session = IngestSession(session_id, self.backend)
        if not self.backend.exists(session._key("meta.json")):
            return None
        return session

    def save_upload(self, session: IngestSession, filename: str, content: bytes) -> list[dict]:
        suffix = Path(filename).suffix.lower()

        if suffix == ".zip":
            return self._handle_zip(session, filename, content)

        if suffix not in (".pdf", ".docx"):
            raise ValueError(f"Unsupported file type: {suffix}")

        file_id = str(uuid.uuid4())
        file_type = suffix.lstrip(".")
        entry = session.add_file(file_id, filename, len(content), file_type)
        self.backend.write_bytes(session.get_upload_key(file_id), content)
        return [entry]

    def _handle_zip(self, session: IngestSession, zip_filename: str, content: bytes) -> list[dict]:
        import tempfile
        import zipfile

        entries = []
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.infolist():
                    name = member.filename
                    if "__MACOSX" in name or name.startswith("."):
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix not in (".pdf", ".docx"):
                        continue

                    file_id = str(uuid.uuid4())
                    file_type = suffix.lstrip(".")
                    inner_filename = Path(name).name
                    file_bytes = zf.read(member)

                    entry = session.add_file(file_id, inner_filename, len(file_bytes), file_type)
                    self.backend.write_bytes(session.get_upload_key(file_id), file_bytes)
                    entries.append(entry)
        finally:
            tmp_path.unlink(missing_ok=True)

        return entries

    def classify_all(self, session: IngestSession) -> dict:
        from src.library.ingester import LibraryIngester

        existing_folders = sorted(
            f.name for f in self.library_path.iterdir() if f.is_dir()
        ) if self.library_path and self.library_path.exists() else []

        ingester = LibraryIngester(library_path=self.library_path)
        results: dict[str, str] = {}
        files = session.get_files()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue

            # Download to temp file for classification
            file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
            if not file_bytes:
                continue

            import tempfile
            ext = entry.get("type", "pdf")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                folder = ingester._classify_file(tmp_path, existing_folders)
                if folder and folder not in existing_folders:
                    existing_folders.append(folder)
            except Exception:
                folder = None
            finally:
                tmp_path.unlink(missing_ok=True)

            session.update_file(file_id, {
                "state": "classified",
                "assigned_folder": folder,
                "is_new_folder": folder not in existing_folders if folder else False,
            })
            results[file_id] = folder

        return results

    def extract_all(self, session: IngestSession, workers: int = 5) -> dict:
        from src.library.builder import LibraryBuilder

        builder = LibraryBuilder(library_path=self.library_path)
        files = session.get_files()
        candidates = {
            fid: entry for fid, entry in files.items()
            if not entry.get("excluded")
        }

        results: dict[str, str] = {}

        def _extract_one(file_id: str, entry: dict) -> tuple[str, str, Optional[dict]]:
            file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
            if not file_bytes:
                return file_id, "failed", {"error": "File not found in storage"}

            import tempfile
            ext = entry.get("type", "pdf")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                data = builder._process_file(tmp_path)
                return file_id, "extracted", data
            except Exception as e:
                return file_id, "failed", {"error": str(e)}
            finally:
                tmp_path.unlink(missing_ok=True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_extract_one, fid, entry): fid
                for fid, entry in candidates.items()
            }

            for future in as_completed(future_map):
                file_id, status, data = future.result()

                if status == "extracted" and data:
                    self.backend.write_json(session.get_extracted_key(file_id), data)
                    session.update_file(file_id, {"state": "extracted"})
                else:
                    if data:
                        self.backend.write_json(session.get_extracted_key(file_id), data)
                    session.update_file(file_id, {"state": "failed"})

                results[file_id] = status

        return results

    def get_extraction_status(self, session: IngestSession) -> dict:
        files = session.get_files()
        status: dict[str, dict] = {}

        for file_id, entry in files.items():
            record: dict = {
                "file_id": file_id,
                "filename": entry.get("filename"),
                "state": entry.get("state"),
                "assigned_folder": entry.get("assigned_folder"),
            }

            data = self.backend.read_json(session.get_extracted_key(file_id))
            record["data"] = data
            status[file_id] = record

        return status

    def save_extracted_edits(self, session: IngestSession, file_id: str, data: dict):
        self.backend.write_json(session.get_extracted_key(file_id), data)

    def persist(self, session: IngestSession) -> dict:
        from src.library.ui.services.db_service import LibraryDBService

        db_service = LibraryDBService(self.backend)
        files = session.get_files()
        persisted_count = 0
        affected_cities: set[str] = set()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue
            folder = entry.get("assigned_folder")
            if not folder:
                continue

            data = self.backend.read_json(session.get_extracted_key(file_id))
            if not data:
                continue

            for field in self._CITY_FIELDS:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    city_raw = item.get("city", "").strip()
                    city = city_raw.title() if city_raw else folder

                    city_data = db_service.get_city_data(city)
                    if city_data is None:
                        city_data = self._empty_city_shard()

                    field_key = "item" if field == "souvenirs" else "name"
                    if not self._is_duplicate(city_data.get(field, []), item, field_key):
                        city_data.setdefault(field, []).append(item)

                    db_service.save_city_data(city, city_data)
                    db_service.set_review_status(city, "pending")
                    affected_cities.add(city)

            for field in self._MULTI_CITY_FIELDS:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    raw_cities = item.get("cities") or []
                    if not raw_cities:
                        raw_cities = [folder]

                    for city_raw in raw_cities:
                        city = city_raw.strip().title() if city_raw.strip() else folder

                        city_data = db_service.get_city_data(city)
                        if city_data is None:
                            city_data = self._empty_city_shard()

                        city_data.setdefault(field, []).append(item)
                        db_service.save_city_data(city, city_data)
                        db_service.set_review_status(city, "pending")
                        affected_cities.add(city)

            # Move source file to aig-library (only if local filesystem)
            if self.library_path:
                file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
                if file_bytes:
                    dest_dir = self.library_path / folder
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest_file = dest_dir / entry.get("filename", f"{file_id}.pdf")
                    if not dest_file.exists():
                        dest_file.write_bytes(file_bytes)

            rel_key = f"{folder}/{entry.get('filename', '')}"
            covered = data.get("covered_cities", [])
            db_service._index.setdefault("_processed_files", {})[rel_key] = {
                "mtime": datetime.now(timezone.utc).timestamp(),
                "destination": folder,
                "covered_cities": covered,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            folder_coverage = db_service._index.setdefault("_folder_coverage", {})
            existing_cities = folder_coverage.get(folder, [])
            for city in covered:
                if city not in existing_cities:
                    existing_cities.append(city)
            folder_coverage[folder] = existing_cities

            persisted_count += 1

        db_service._save_index()
        session.cleanup()

        return {
            "persisted_files": persisted_count,
            "affected_cities": sorted(affected_cities),
        }

    def _empty_city_shard(self) -> dict:
        return {
            "restaurants": [],
            "attractions": [],
            "hotels": [],
            "local_dishes": [],
            "souvenirs": [],
            "phrases": [],
            "safety_tips": [],
            "connectivity_tips": [],
            "health_tips": [],
            "emergency_contacts": [],
            "transport_options": [],
            "source_files": [],
        }

    def _is_duplicate(self, existing_items: list, new_item: dict, field: str = "name") -> bool:
        new_val = (new_item.get(field) or "").strip().lower()
        if not new_val:
            return False
        for item in existing_items:
            if isinstance(item, dict):
                existing_val = (item.get(field) or "").strip().lower()
                if existing_val == new_val:
                    return True
        return False
```

- [ ] **Step 3: Update imports at top of file**

The file header should be:

```python
"""Ingest service: session management, classify, extract, and persist for the ingest wizard."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..storage import StorageBackend
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/library/ui/services/ingest_service.py
git commit -m "refactor(ingest-service): use StorageBackend for session and file I/O"
```

---

### Task 7: Refactor country_extractor to Use StorageBackend

**Files:**
- Modify: `src/library/ui/services/country_extractor.py`

- [ ] **Step 1: Rewrite to accept StorageBackend**

Replace `src/library/ui/services/country_extractor.py`:

```python
from ..storage import StorageBackend

COUNTRY_LEVEL_FIELDS = [
    "connectivity_tips",
    "safety_tips",
    "health_tips",
    "phrases",
    "emergency_contacts",
    "transport_options",
]


def extract_country_data(backend: StorageBackend, folder_name: str, city_names: list[str]) -> dict:
    """Aggregate country-level data from city shards for a given folder/country."""
    country_data: dict[str, list] = {field: [] for field in COUNTRY_LEVEL_FIELDS}
    seen_tips: dict[str, set] = {field: set() for field in COUNTRY_LEVEL_FIELDS}

    for city in city_names:
        shard = backend.read_json(f"{city}.json")
        if not shard:
            continue

        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key_val = (item.get(key_field) or "").strip().lower()
                    if key_val and key_val not in seen_tips[field]:
                        seen_tips[field].add(key_val)
                        country_data[field].append(item)
                else:
                    country_data[field].append(item)

    return country_data


def ensure_country_shards(backend: StorageBackend):
    """Generate country-level shards from city data if they don't exist."""
    from .db_service import LibraryDBService

    db = LibraryDBService(backend)
    coverage = db.get_folder_coverage()

    for folder, cities in coverage.items():
        country_name = folder.replace("-", " ").title()
        existing = backend.read_json(f"_country/{country_name}.json")
        if existing:
            continue

        country_data = extract_country_data(backend, folder, cities)
        has_content = any(len(v) > 0 for v in country_data.values())
        if has_content:
            backend.write_json(f"_country/{country_name}.json", country_data)
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/library/ui/services/country_extractor.py
git commit -m "refactor(country-extractor): use StorageBackend instead of filesystem Path"
```

---

### Task 8: Update create_app() and All API Routes

**Files:**
- Modify: `src/library/ui/__init__.py`
- Modify: `src/library/ui/api/tree.py`
- Modify: `src/library/ui/api/city.py`
- Modify: `src/library/ui/api/country.py`
- Modify: `src/library/ui/api/review.py`
- Modify: `src/library/ui/api/sweep.py`
- Modify: `src/library/ui/api/audit.py`
- Modify: `src/library/ui/api/ingest.py`

- [ ] **Step 1: Update create_app() to accept optional StorageBackend**

Replace `src/library/ui/__init__.py`:

```python
"""FastAPI application factory for the Library QC UI."""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import tree, city, country, review, sweep, audit, ingest
from .storage import LocalStorageBackend, StorageBackend


def create_app(
    db_path: Optional[Path] = None,
    library_path: Path = Path("aig-library"),
    storage_backend: Optional[StorageBackend] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the library database directory (local dev).
        library_path: Path to the AIG library directory.
        storage_backend: Pre-configured storage backend (Lambda). Overrides db_path.
    """
    app = FastAPI(
        title="Library QC UI",
        description="Quality control interface for the AIG library database",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if storage_backend is None:
        if db_path is None:
            db_path = Path("library_db")
        storage_backend = LocalStorageBackend(db_path)

    app.state.storage_backend = storage_backend
    app.state.library_path = library_path

    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")

    from fastapi.staticfiles import StaticFiles

    dist_path = Path(__file__).parent.parent.parent.parent / "ui-frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    return app
```

- [ ] **Step 2: Update api/tree.py**

```python
from fastapi import APIRouter, Request

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/tree")
def get_tree(request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    return db.get_tree()
```

- [ ] **Step 3: Update api/city.py**

```python
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..services.db_service import LibraryDBService
from ..services.audit_service import AuditService

router = APIRouter()


class DeleteItemRequest(BaseModel):
    reason: str
    deleted_by: str = "unknown"


@router.get("/city/{name}")
def get_city(name: str, request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    return data


@router.put("/city/{name}")
def save_city(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.storage_backend)
    existing = db.get_city_data(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    db.save_city_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}


@router.delete("/city/{name}/{category}/{index}")
def delete_item(name: str, category: str, index: int, request: Request, body: DeleteItemRequest):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    items = data.get(category, [])
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail=f"Item index {index} out of range")

    deleted_item = items.pop(index)
    db.save_city_data(name, data)

    audit = AuditService(request.app.state.storage_backend)
    audit.log_deletion(
        category=category,
        city=name,
        item_name=deleted_item.get("name", "unknown"),
        reason=body.reason,
        item_snapshot=deleted_item,
        deleted_by=body.deleted_by,
    )
    db.set_review_status(name, "in_progress")
    return {"status": "deleted"}
```

- [ ] **Step 4: Update api/country.py**

```python
from fastapi import APIRouter, Request, HTTPException

from ..services.db_service import LibraryDBService
from ..services.country_extractor import ensure_country_shards

router = APIRouter()


@router.get("/country/{name}")
def get_country(name: str, request: Request):
    backend = request.app.state.storage_backend
    ensure_country_shards(backend)
    db = LibraryDBService(backend)
    data = db.get_country_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Country '{name}' not found")
    return data


@router.put("/country/{name}")
def save_country(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.storage_backend)
    db.save_country_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}
```

- [ ] **Step 5: Update api/sweep.py**

```python
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from typing import Optional

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/sweep")
def get_sweep(
    request: Request,
    category: str = Query(..., description="e.g. restaurants, attractions"),
    field: Optional[str] = Query(None, description="e.g. vegetarian_friendly, hours"),
    filter: Optional[str] = Query(None, description="all, missing, unchecked, checked"),
):
    db = LibraryDBService(request.app.state.storage_backend)
    results = []

    all_cities = db.get_all_city_names()
    for city_name in all_cities:
        data = db.get_city_data(city_name)
        if not data:
            continue
        items = data.get(category, [])
        for idx, item in enumerate(items):
            if field and filter and filter != "all":
                value = item.get(field)
                if filter == "missing" and value not in (None, "", []):
                    continue
                if filter == "unchecked" and value is not False:
                    continue
                if filter == "checked" and value is not True:
                    continue

            results.append({
                "city": city_name,
                "index": idx,
                "item": item,
            })

    return {
        "category": category,
        "field": field,
        "filter": filter,
        "total": len(results),
        "items": results,
    }


class SweepSaveRequest(BaseModel):
    edits: list[dict]


@router.put("/sweep")
def save_sweep(request: Request, body: SweepSaveRequest):
    db = LibraryDBService(request.app.state.storage_backend)
    affected_cities: set[str] = set()

    for edit in body.edits:
        city = edit["city"]
        index = edit["index"]
        category = edit["category"]
        field_name = edit["field"]
        value = edit["value"]

        data = db.get_city_data(city)
        if not data:
            continue
        items = data.get(category, [])
        if index < 0 or index >= len(items):
            continue
        items[index][field_name] = value
        db.save_city_data(city, data)
        affected_cities.add(city)

    for city in affected_cities:
        db.set_review_status(city, "in_progress")

    return {"status": "saved", "affected_cities": len(affected_cities)}
```

- [ ] **Step 6: Update api/audit.py**

Read the current file first, then update. The pattern is the same — replace `AuditService(request.app.state.db_path)` with `AuditService(request.app.state.storage_backend)`.

- [ ] **Step 7: Update api/review.py**

Same pattern — replace `LibraryDBService(request.app.state.db_path)` with `LibraryDBService(request.app.state.storage_backend)`.

- [ ] **Step 8: Update api/ingest.py**

Replace the `_get_service` helper and folder/history endpoints:

```python
"""Ingest wizard API endpoints."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..services.ingest_service import IngestService

router = APIRouter(prefix="/ingest")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _get_service(request: Request) -> IngestService:
    backend = request.app.state.storage_backend
    library_path = Path(request.app.state.library_path)
    return IngestService(backend, library_path)


class FileUpdateRequest(BaseModel):
    assigned_folder: Optional[str] = None
    excluded: Optional[bool] = None


@router.post("/upload")
async def upload_files(request: Request, files: list[UploadFile] = File(...)):
    service = _get_service(request)
    session = service.create_session()

    all_entries: list[dict] = []
    for upload in files:
        content = await upload.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"File {upload.filename!r} exceeds 50 MB limit")
        entries = service.save_upload(session, upload.filename or "upload", content)
        all_entries.extend(entries)

    return {"session_id": session.session_id, "files": all_entries}


@router.post("/{session_id}/upload")
async def upload_to_session(session_id: str, request: Request, files: list[UploadFile] = File(...)):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    all_entries: list[dict] = []
    for upload in files:
        content = await upload.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"File {upload.filename!r} exceeds 50 MB limit")
        entries = service.save_upload(session, upload.filename or "upload", content)
        all_entries.extend(entries)

    return {"session_id": session_id, "files": all_entries}


@router.delete("/{session_id}/files/{file_id}")
def delete_file(session_id: str, file_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entry = session.get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    session.remove_file(file_id)
    return {"status": "deleted", "files": list(session.get_files().values())}


@router.put("/{session_id}/files/{file_id}")
def update_file(session_id: str, file_id: str, body: FileUpdateRequest, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entry = session.get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    updates: dict = {}
    if body.excluded is not None:
        updates["excluded"] = body.excluded
    if body.assigned_folder is not None:
        updates["assigned_folder"] = body.assigned_folder
        updates["state"] = "classified"
        library_path = Path(request.app.state.library_path)
        updates["is_new_folder"] = not (library_path / body.assigned_folder).exists()

    if updates:
        session.update_file(file_id, updates)

    return session.get_file(file_id)


@router.post("/{session_id}/classify")
def classify(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service.classify_all(session)
    return {"files": list(session.get_files().values())}


@router.post("/{session_id}/extract")
def extract(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service.extract_all(session)
    return {"status": "complete"}


@router.get("/{session_id}/extract/status")
def extract_status(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    status = service.get_extraction_status(session)
    return {"files": list(status.values())}


@router.put("/{session_id}/files/{file_id}/data")
def save_file_data(session_id: str, file_id: str, request: Request, body: dict):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entry = session.get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    service.save_extracted_edits(session, file_id, body)
    return {"status": "saved"}


@router.post("/{session_id}/persist")
def persist(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result = service.persist(session)
    return result if result is not None else {"status": "ok"}


@router.get("/folders")
def list_folders(request: Request):
    library_path = Path(request.app.state.library_path)
    if not library_path.exists():
        return {"folders": []}

    folders = sorted(entry.name for entry in library_path.iterdir() if entry.is_dir())
    return {"folders": folders}


@router.get("/history")
def ingest_history(request: Request):
    backend = request.app.state.storage_backend
    index = backend.read_json("_index.json")
    if not index:
        return {"files": []}

    processed = index.get("_processed_files", {})
    files = []
    for filename, meta in processed.items():
        files.append({
            "filename": filename,
            "destination": meta.get("destination", ""),
            "covered_cities": meta.get("covered_cities", []),
            "ingested_at": meta.get("processed_at", ""),
        })

    files.sort(key=lambda x: x["ingested_at"] or "", reverse=True)
    return {"files": files}
```

- [ ] **Step 9: Run all tests and verify local server starts**

Run: `pytest tests/ -v`
Expected: All tests pass

Run: `python -c "from src.library.ui import create_app; app = create_app()" `
Expected: No import errors

- [ ] **Step 10: Commit**

```bash
git add src/library/ui/__init__.py src/library/ui/api/
git commit -m "refactor(api): wire all routes to use StorageBackend via app.state"
```

---

### Task 9: Lambda Handler

**Files:**
- Create: `src/library/ui/lambda_handler.py`

- [ ] **Step 1: Create the Mangum handler**

```python
"""AWS Lambda entry point — Mangum wraps the FastAPI app."""

import os

from mangum import Mangum

from . import create_app
from .storage import get_storage_backend

backend = get_storage_backend()

library_path = None
if os.environ.get("LIBRARY_PATH"):
    from pathlib import Path
    library_path = Path(os.environ["LIBRARY_PATH"])

app = create_app(storage_backend=backend, library_path=library_path or "aig-library")
handler = Mangum(app)
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from src.library.ui.lambda_handler import handler; print('OK')"`
Expected: This will fail because `AWS_LAMBDA_FUNCTION_NAME` isn't set, so it uses `LocalStorageBackend` which is fine. Should print "OK".

Note: If it fails due to missing `mangum`, install it: `pip install mangum`

- [ ] **Step 3: Commit**

```bash
git add src/library/ui/lambda_handler.py
git commit -m "feat(lambda): add Mangum handler entry point"
```

---

### Task 10: Presigned Upload API Endpoint

**Files:**
- Modify: `src/library/ui/api/ingest.py` (add presigned endpoint)
- Modify: `src/library/ui/storage.py` (add `generate_presigned_put` to LocalStorageBackend as no-op)

- [ ] **Step 1: Add generate_presigned_put to StorageBackend ABC and LocalStorageBackend**

Add to the `StorageBackend` ABC (not abstract — optional, with a default that raises):

```python
def generate_presigned_put(self, key: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> Optional[str]:
    """Generate a presigned PUT URL. Returns None if not supported (local backend)."""
    return None
```

`LocalStorageBackend` inherits the default (returns None). `S3StorageBackend` already implements it.

- [ ] **Step 2: Add presigned upload endpoint to api/ingest.py**

Add after the existing `upload_files` endpoint:

```python
class PresignedUploadRequest(BaseModel):
    files: list[dict]  # [{"filename": "foo.pdf", "size": 12345, "content_type": "application/pdf"}, ...]


@router.post("/upload/presigned")
def get_presigned_upload_urls(request: Request, body: PresignedUploadRequest):
    """Generate presigned PUT URLs for direct-to-S3 upload.
    
    Falls back to regular upload flow if backend doesn't support presigned URLs.
    """
    backend = request.app.state.storage_backend
    service = _get_service(request)
    session = service.create_session()

    files_info = []
    for file_spec in body.files:
        filename = file_spec["filename"]
        content_type = file_spec.get("content_type", "application/octet-stream")
        suffix = Path(filename).suffix.lower()
        file_type = suffix.lstrip(".")
        file_id = str(__import__("uuid").uuid4())

        # Register file in session meta
        size = file_spec.get("size", 0)
        session.add_file(file_id, filename, size, file_type)

        # Generate presigned URL
        upload_key = session.get_upload_key(file_id)
        presigned_url = backend.generate_presigned_put(upload_key, content_type=content_type)

        files_info.append({
            "file_id": file_id,
            "filename": filename,
            "presigned_url": presigned_url,
            "upload_key": upload_key,
        })

    return {
        "session_id": session.session_id,
        "files": files_info,
        "use_presigned": files_info[0]["presigned_url"] is not None if files_info else False,
    }


@router.post("/{session_id}/upload/confirm")
def confirm_presigned_upload(session_id: str, request: Request):
    """Confirm that presigned uploads completed. Updates file states."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify files exist in storage
    backend = request.app.state.storage_backend
    files = session.get_files()
    confirmed = []
    for file_id, entry in files.items():
        key = session.get_upload_key(file_id)
        if backend.exists(key):
            session.update_file(file_id, {"state": "uploaded"})
            confirmed.append(entry)

    return {"session_id": session_id, "files": list(session.get_files().values())}
```

- [ ] **Step 3: Commit**

```bash
git add src/library/ui/api/ingest.py src/library/ui/storage.py
git commit -m "feat(ingest): add presigned URL upload endpoints for Lambda"
```

---

### Task 11: Frontend — Presigned Upload Flow

**Files:**
- Modify: `ui-frontend/src/api/client.ts`

- [ ] **Step 1: Add presigned upload methods to API client**

Add to the `api` object in `client.ts`:

```typescript
  ingestPresignedUpload: async (files: File[]): Promise<{ session_id: string; files: any[]; use_presigned: boolean }> => {
    const fileSpecs = files.map(f => ({
      filename: f.name,
      size: f.size,
      content_type: f.type || "application/octet-stream",
    }));
    return request(`/ingest/upload/presigned`, {
      method: "POST",
      body: JSON.stringify({ files: fileSpecs }),
    });
  },

  ingestUploadToPresigned: async (presignedUrl: string, file: File): Promise<void> => {
    const res = await fetch(presignedUrl, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    });
    if (!res.ok) throw new Error(`Presigned upload failed: ${res.status}`);
  },

  ingestConfirmUpload: (sessionId: string) =>
    request<{ session_id: string; files: any[] }>(`/ingest/${sessionId}/upload/confirm`, { method: "POST" }),
```

- [ ] **Step 2: Update ingestUpload to try presigned first, fall back to FormData**

Replace the existing `ingestUpload` method:

```typescript
  ingestUpload: async (files: File[]): Promise<{ session_id: string; files: any[] }> => {
    // Try presigned upload first (works on Lambda with S3)
    try {
      const presignedResp = await api.ingestPresignedUpload(files);
      if (presignedResp.use_presigned) {
        // Upload each file directly to S3 via presigned URL
        const filesByName = Object.fromEntries(files.map(f => [f.name, f]));
        await Promise.all(
          presignedResp.files.map(info => {
            const file = filesByName[info.filename];
            if (file && info.presigned_url) {
              return api.ingestUploadToPresigned(info.presigned_url, file);
            }
            return Promise.resolve();
          })
        );
        // Confirm uploads landed
        return api.ingestConfirmUpload(presignedResp.session_id);
      }
    } catch {
      // Fall through to FormData upload
    }

    // Fallback: direct FormData upload (local dev)
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const res = await fetch(`${BASE}/ingest/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
```

- [ ] **Step 3: Build frontend**

Run from `ui-frontend/`:
```bash
cd ui-frontend && npm run build
```
Expected: Build succeeds, `dist/` updated

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/api/client.ts
git commit -m "feat(frontend): add presigned upload with FormData fallback"
```

---

### Task 12: Build Script

**Files:**
- Create: `deploy/aws/build-deploy-lambda.sh`
- Create: `deploy/aws/lambda-requirements.txt`

- [ ] **Step 1: Create lambda-requirements.txt**

```
mangum>=0.17.0
boto3>=1.35.0
fastapi>=0.115.0
python-multipart>=0.0.9
pydantic>=2.0.0
openai>=1.0.0
pymupdf>=1.24.0
pdfplumber>=0.11.0
python-docx>=1.1.0
python-dotenv>=1.0.0
requests>=2.31.0
rich>=13.0.0
```

Note: `uvicorn` is excluded (not needed on Lambda). `anthropic` excluded if not directly imported at runtime.

- [ ] **Step 2: Create build-deploy-lambda.sh**

```bash
#!/usr/bin/env bash
# Build a versioned Lambda zip for the Library QC UI.
#
# Usage:
#   ./deploy/aws/build-deploy-lambda.sh
#   ./deploy/aws/build-deploy-lambda.sh --upload
#   ./deploy/aws/build-deploy-lambda.sh --deploy --function-name library-qc
#
# Environment (optional overrides):
#   AWS_PROFILE          default: bvbm
#   AWS_REGION           default: ap-south-1
#   LAMBDA_FUNCTION_NAME  default: empty; required for --deploy unless --function-name is set

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bvbm}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

S3_DEPLOY_BUCKET="bvbm-code"
S3_DEPLOY_PREFIX="library-qc"

LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-}"

read_package_version() {
  if [[ -f "$REPO_ROOT/VERSION" ]]; then
    head -n1 "$REPO_ROOT/VERSION" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
  elif v=$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null); then
    echo "$v"
  else
    echo "0.0.0"
  fi
}

safe_version_slug() {
  echo "$1" | tr -c 'A-Za-z0-9._-' '-' | sed -e 's/--*/-/g' -e 's/^-//' -e 's/-$//'
}

PACKAGE_VERSION=$(read_package_version)
VERSION_SLUG=$(safe_version_slug "$PACKAGE_VERSION")
[[ -z "$VERSION_SLUG" ]] && VERSION_SLUG="0"
BUILD_ID=$(date -u +%Y%m%dT%H%M%SZ)
ZIP_BASENAME="function-${VERSION_SLUG}-${BUILD_ID}.zip"

UPLOAD_S3=false
DEPLOY_LAMBDA=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload) UPLOAD_S3=true ;;
    --deploy)
      DEPLOY_LAMBDA=true
      UPLOAD_S3=true
      ;;
    --function-name)
      [[ $# -ge 2 ]] || { echo "Missing value for --function-name" >&2; exit 1; }
      LAMBDA_FUNCTION_NAME="$2"
      shift 2
      continue
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--upload] [--deploy [--function-name NAME]]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

echo "==> Repository root: $REPO_ROOT"
echo "==> AWS_PROFILE=${AWS_PROFILE}  AWS_REGION=${AWS_REGION}"
cd "$REPO_ROOT"
mkdir -p build

echo "==> Package version: $PACKAGE_VERSION  (artifact: $ZIP_BASENAME)"

echo "==> Cleaning build/lambda"
rm -rf build/lambda
mkdir -p build/lambda

echo "==> Installing dependencies (manylinux2014_aarch64, cp314)"
python3 -m pip install \
  -r deploy/aws/lambda-requirements.txt \
  --platform manylinux2014_aarch64 \
  --python-version 314 \
  --implementation cp \
  --only-binary=:all: \
  -t build/lambda/ \
  --quiet

echo "==> Copying application code into build/lambda"
cp -R src build/lambda/

echo "==> Building frontend"
if [[ -d "ui-frontend" ]]; then
  (cd ui-frontend && npm run build)
  cp -R ui-frontend/dist build/lambda/ui-frontend/dist
  mkdir -p build/lambda/ui-frontend
  cp -R ui-frontend/dist build/lambda/ui-frontend/
fi

echo "==> Removing __pycache__ and .pyc"
find build/lambda -depth -type d -name '__pycache__' -exec rm -rf {} \;
find build/lambda -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

echo "==> Creating build/$ZIP_BASENAME"
(cd build/lambda && zip -qr "../$ZIP_BASENAME" .)

cp -f "$REPO_ROOT/build/$ZIP_BASENAME" "$REPO_ROOT/build/function.zip"
echo "$ZIP_BASENAME" > "$REPO_ROOT/build/.lambda-package-latest.txt"

echo "==> Artifact: build/$ZIP_BASENAME"
ls -lh "$REPO_ROOT/build/$ZIP_BASENAME"

S3_KEY="${S3_DEPLOY_PREFIX}/${ZIP_BASENAME}"

if "$UPLOAD_S3"; then
  S3_URI="s3://${S3_DEPLOY_BUCKET}/${S3_KEY}"
  echo "==> Uploading to ${S3_URI}"
  aws s3 cp "$REPO_ROOT/build/$ZIP_BASENAME" "$S3_URI"
fi

if "$DEPLOY_LAMBDA"; then
  if [[ -z "${LAMBDA_FUNCTION_NAME}" ]]; then
    echo "error: --deploy requires --function-name NAME or env LAMBDA_FUNCTION_NAME" >&2
    exit 1
  fi
  echo "==> Updating Lambda: ${LAMBDA_FUNCTION_NAME}"
  aws lambda update-function-code \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --s3-bucket "$S3_DEPLOY_BUCKET" \
    --s3-key "$S3_KEY" \
    --region "$AWS_REGION"
  echo "==> Done."
fi
```

- [ ] **Step 3: Make executable**

```bash
chmod +x deploy/aws/build-deploy-lambda.sh
```

- [ ] **Step 4: Commit**

```bash
git add deploy/aws/build-deploy-lambda.sh deploy/aws/lambda-requirements.txt
git commit -m "feat(deploy): add Lambda build script and requirements"
```

---

### Task 13: SAM Template + QUICKSTART

**Files:**
- Create: `deploy/aws/sam-template.yaml`
- Create: `deploy/aws/QUICKSTART.md`

- [ ] **Step 1: Create SAM template**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Library QC UI (FastAPI + Mangum)

Globals:
  Function:
    Timeout: 900
    MemorySize: 1024

Resources:
  LibraryQCFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: src.library.ui.lambda_handler.handler
      Runtime: python3.14
      Architectures:
        - arm64
      EphemeralStorage:
        Size: 512
      Environment:
        Variables:
          LIBRARY_S3_BUCKET: bvbm-library
          LIBRARY_S3_PREFIX: library_db
      FunctionUrlConfig:
        AuthType: NONE
        Cors:
          AllowOrigins:
            - '*'
          AllowMethods:
            - '*'
          AllowHeaders:
            - '*'
      Policies:
        - AWSLambdaBasicExecutionRole
        - S3CrudPolicy:
            BucketName: bvbm-library

Outputs:
  FunctionName:
    Description: Lambda function name
    Value: !Ref LibraryQCFunction
  FunctionUrl:
    Description: Public HTTPS URL
    Value: !GetAtt LibraryQCFunctionUrl.FunctionUrl
```

- [ ] **Step 2: Create QUICKSTART.md**

```markdown
# Library QC UI — AWS Deployment

## Prerequisites

- AWS CLI configured with profile `bvbm` (region `ap-south-1`)
- Python 3.14+, Node.js 18+ (for frontend build)
- S3 bucket `bvbm-library` created in `ap-south-1`

## Initial Setup

### 1. Create S3 bucket

```bash
aws s3 mb s3://bvbm-library --region ap-south-1 --profile bvbm
```

### 2. Upload existing library_db

```bash
aws s3 sync library_db/ s3://bvbm-library/library_db/ \
  --exclude "_staging/*" \
  --profile bvbm --region ap-south-1
```

### 3. Create Lambda function

```bash
# Build the deployment zip
./deploy/aws/build-deploy-lambda.sh

# Create the function (first time)
aws lambda create-function \
  --function-name library-qc \
  --runtime python3.14 \
  --architectures arm64 \
  --handler src.library.ui.lambda_handler.handler \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-library-qc \
  --zip-file fileb://build/function.zip \
  --timeout 900 \
  --memory-size 1024 \
  --environment "Variables={LIBRARY_S3_BUCKET=bvbm-library,LIBRARY_S3_PREFIX=library_db,AI_API_KEY=...,AI_BASE_URL=...,AI_MODEL=claude-sonnet-4-20250514}" \
  --region ap-south-1 \
  --profile bvbm
```

### 4. Create Function URL

```bash
aws lambda create-function-url-config \
  --function-name library-qc \
  --auth-type NONE \
  --cors "AllowOrigins=*,AllowMethods=*,AllowHeaders=*" \
  --region ap-south-1 \
  --profile bvbm
```

### 5. Add resource policy for public access

```bash
aws lambda add-permission \
  --function-name library-qc \
  --statement-id FunctionURLPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region ap-south-1 \
  --profile bvbm
```

## Subsequent Deploys

```bash
./deploy/aws/build-deploy-lambda.sh --deploy --function-name library-qc
```

## IAM Role

The Lambda execution role needs:
- `AWSLambdaBasicExecutionRole` (CloudWatch logs)
- S3 access to `bvbm-library` bucket:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::bvbm-library",
    "arn:aws:s3:::bvbm-library/*"
  ]
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LIBRARY_S3_BUCKET` | Yes | S3 bucket name |
| `LIBRARY_S3_PREFIX` | No | Key prefix (default: `library_db`) |
| `AI_API_KEY` | Yes | For classify/extract AI calls |
| `AI_BASE_URL` | Yes | OpenAI-compatible endpoint |
| `AI_MODEL` | Yes | Model name |
| `GOOGLE_MAPS_API_KEY` | No | For geocoding |
```

- [ ] **Step 3: Commit**

```bash
git add deploy/aws/sam-template.yaml deploy/aws/QUICKSTART.md
git commit -m "feat(deploy): add SAM template and QUICKSTART guide"
```

---

### Task 14: Local Verification — Full Roundtrip

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 2: Start local server and verify QC UI works**

```bash
python -m src.library.ui.server
```

Open `http://localhost:8765` in browser. Verify:
- Tree loads with cities
- Click a city → data loads
- Edit a field → save works
- Ingest tab → upload a file → classify → extract → persist

- [ ] **Step 3: Verify build script runs**

```bash
./deploy/aws/build-deploy-lambda.sh
```

Expected: `build/function.zip` created, no errors

- [ ] **Step 4: Commit any fixes, then final commit message**

```bash
git add -A
git commit -m "chore: final verification and fixes for Lambda deployment"
```
