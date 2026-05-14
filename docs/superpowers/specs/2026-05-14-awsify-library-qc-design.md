# AWSify Library QC UI — Design Spec

**Date:** 2026-05-14  
**Status:** Draft  
**Reference:** `presentations` project deployment pattern (`deploy/aws/`)

## Goal

Deploy the Library QC UI (FastAPI backend + React frontend) to AWS Lambda with a Function URL, storing `library_db/` in S3. Single-user, cost-optimized deployment mirroring the proven `presentations` project architecture.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Lambda (arm64)                     │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Mangum adapter                                     │ │
│  │  ┌───────────────────────────────────────────────┐  │ │
│  │  │  FastAPI app                                  │  │ │
│  │  │  ├── /api/* routes (QC, ingest, etc.)         │  │ │
│  │  │  └── /* static (React SPA from bundled dist/) │  │ │
│  │  └───────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
         │                          │
    Function URL              boto3 S3 calls
    (HTTPS, no auth)                │
         │                          ▼
    Browser ◄──────────────── S3 Bucket
                              ├── library_db/
                              │   ├── _index.json
                              │   ├── amsterdam.json
                              │   ├── rome.json
                              │   └── ...
                              └── staging/
                                  └── {session_id}/
                                      ├── meta.json
                                      └── uploads/...
```

---

## Components

### 1. Lambda Function

| Setting | Value |
|---------|-------|
| Runtime | Python 3.14 |
| Architecture | arm64 (Graviton, ~20% cheaper) |
| Memory | 1024 MB |
| Timeout | 900s (15 min, for AI extraction) |
| Ephemeral storage | 512 MB (default, for /tmp during extraction) |
| Handler | `src.library.ui.lambda_handler.handler` |

### 2. Function URL

- Auth: NONE (same as presentations — no API Gateway needed)
- CORS: allow all origins/methods/headers (single-user tool)
- Streaming: not required (all responses are JSON or static files)

### 3. S3 Bucket

Single bucket, prefix-based separation:

| Prefix | Contents |
|--------|----------|
| `library_db/` | City JSON shards + `_index.json` |
| `library_db/_staging/{session_id}/` | Ingest wizard uploads + meta |

Bucket: `bvbm-library` (or reuse existing `bvbm-code` with a `library/` prefix)

### 4. Frontend

Bundled in the Lambda deployment zip at `ui-frontend/dist/`. Served by FastAPI's `StaticFiles` exactly as it works today. No S3+CloudFront — unnecessary for single-user.

---

## Storage Abstraction

The critical code change: `LibraryDBService` and `IngestService` currently use `Path` and filesystem I/O. We need an abstraction layer so the same service code works locally (filesystem) and on Lambda (S3).

### Interface: `StorageBackend`

```python
from abc import ABC, abstractmethod
from pathlib import PurePosixPath

class StorageBackend(ABC):
    """Unified storage interface for local filesystem and S3."""

    @abstractmethod
    def read_json(self, key: str) -> dict | None:
        """Read and parse a JSON file. Returns None if not found."""

    @abstractmethod
    def write_json(self, key: str, data: dict) -> None:
        """Serialize and write a JSON file."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes | None:
        """Read raw bytes. Returns None if not found."""

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> None:
        """Write raw bytes."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a file/object."""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """List all keys under a prefix."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
```

### Implementations

**`LocalStorageBackend`** — wraps a base `Path`, maps keys to files. Used for local development. Drop-in replacement for current behavior.

**`S3StorageBackend`** — wraps a bucket + prefix, maps keys to S3 objects via boto3. Used on Lambda (detected via `AWS_LAMBDA_FUNCTION_NAME` env var).

### Backend Selection

```python
def get_storage_backend() -> StorageBackend:
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        bucket = os.environ["LIBRARY_S3_BUCKET"]
        prefix = os.environ.get("LIBRARY_S3_PREFIX", "library_db")
        return S3StorageBackend(bucket, prefix)
    else:
        db_path = os.environ.get("LIBRARY_DB_PATH", "library_db")
        return LocalStorageBackend(Path(db_path))
```

---

## Service Layer Changes

### `LibraryDBService`

Currently takes `db_path: Path` and does `open(path / "file.json")`. Change to accept a `StorageBackend` and use `backend.read_json("amsterdam.json")` instead.

**Methods affected:**
- `_load_index()` → `backend.read_json("_index.json")`
- `_save_index()` → `backend.write_json("_index.json", data)`
- `get_city_data(city)` → `backend.read_json(f"{city}.json")`
- `save_city_data(city, data)` → `backend.write_json(f"{city}.json", data)`
- `list_cities()` → `backend.list_keys("")` filtered to `*.json` excluding `_index.json`

### `IngestService`

Currently uses `self._staging_root = self.db_path / "_staging"`. Change staging to use a separate `StorageBackend` (or same backend with `_staging/` prefix).

**Methods affected:**
- `save_upload()` → `staging_backend.write_bytes(f"{session_id}/uploads/{file_id}.pdf", content)`
- `load_meta()` → `staging_backend.read_json(f"{session_id}/meta.json")`
- File reads during extraction → download from S3 to `/tmp`, process, delete local copy

### `IngestSession`

Refactor to use `StorageBackend` instead of direct `Path` manipulation. The session keeps its file-tracking logic but delegates I/O to the backend.

---

## Lambda Handler

New file: `src/library/ui/lambda_handler.py`

```python
from mangum import Mangum
from . import create_app
from .storage import get_storage_backend

backend = get_storage_backend()
app = create_app(storage_backend=backend)
handler = Mangum(app)
```

`create_app()` gains an optional `storage_backend` parameter. When provided (Lambda), services use it directly. When omitted (local dev via `server.py`), `create_app()` constructs a `LocalStorageBackend` from `db_path` internally. This keeps the local dev entry point (`server.py`) unchanged.

---

## Environment Variables (Lambda)

| Variable | Value | Purpose |
|----------|-------|---------|
| `LIBRARY_S3_BUCKET` | `bvbm-library` | S3 bucket for all data |
| `LIBRARY_S3_PREFIX` | `library_db` | Prefix for city shards |
| `AI_API_KEY` | (secret) | For classification/extraction AI calls |
| `AI_BASE_URL` | (endpoint) | OpenAI-compatible API endpoint |
| `AI_MODEL` | `claude-sonnet-4-20250514` | Model for AI operations |
| `GOOGLE_MAPS_API_KEY` | (secret) | For geocoding (if used in QC) |

---

## Build & Deploy

Mirror the `presentations` project structure:

```
deploy/aws/
├── sam-template.yaml
├── build-deploy-lambda.sh
└── QUICKSTART.md
```

### Build Script

Adapted from presentations:

1. Install dependencies to `build/lambda/` (pip cross-compile for `manylinux2014_aarch64` + `cp314`)
2. Copy application code: `src/`, `ui-frontend/dist/`
3. Strip `__pycache__`, `.pyc`
4. Create versioned zip: `function-{version}-{timestamp}.zip`
5. Optional `--upload` to S3, `--deploy` to update Lambda

### Requirements

Two requirements files:
- `requirements.txt` (existing: openai, pydantic, etc.)
- `deploy/aws/lambda-requirements.txt` (additional: mangum, boto3, fastapi, uvicorn — though uvicorn only needed locally)

Note: `boto3` is pre-installed in the Lambda runtime, so it doesn't need to be in the zip, but we include it for consistent behavior during local testing with the S3 backend.

### SAM Template

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
      Architectures: [arm64]
      EphemeralStorage:
        Size: 512
      Environment:
        Variables:
          LIBRARY_S3_BUCKET: bvbm-library
          LIBRARY_S3_PREFIX: library_db
      FunctionUrlConfig:
        AuthType: NONE
        Cors:
          AllowOrigins: ['*']
          AllowMethods: ['*']
          AllowHeaders: ['*']
      Policies:
        - AWSLambdaBasicExecutionRole
        - S3CrudPolicy:
            BucketName: bvbm-library

Outputs:
  FunctionUrl:
    Value: !GetAtt LibraryQCFunctionUrl.FunctionUrl
```

---

## Migration: Uploading Existing library_db to S3

One-time script to sync local `library_db/` to S3:

```bash
aws s3 sync library_db/ s3://bvbm-library/library_db/ \
  --exclude "_staging/*" \
  --profile bvbm --region ap-south-1
```

---

## Local Development (unchanged workflow)

No changes to local dev workflow:
- `npm run dev` in `ui-frontend/` (Vite dev server on :5173, proxies /api to :8765)
- `python -m src.library.ui.server` (Uvicorn on :8765, uses local filesystem)

The `LocalStorageBackend` is the default when `AWS_LAMBDA_FUNCTION_NAME` is not set. Services work identically.

---

## Ingest Flow on Lambda (detailed)

1. **Upload** — Browser POSTs files → Lambda writes to `s3://bucket/library_db/_staging/{session_id}/uploads/{file_id}.pdf`
2. **Classify** — Lambda reads file metadata from S3 staging, calls AI for classification, returns results
3. **Extract** — Lambda downloads file from S3 staging to `/tmp/{file_id}.pdf`, runs AI extraction (30-60s), returns extracted data for preview
4. **Persist** — Lambda writes finalized city JSON to `s3://bucket/library_db/{city}.json` and updates `_index.json`
5. **Cleanup** — Lambda deletes `s3://bucket/library_db/_staging/{session_id}/` prefix

File size limit: 50 MB (current limit, well within Lambda's 6 MB response payload — but uploads via Function URL support up to 20 MB request body by default, configurable to 20 MB max). For files >6 MB upload: use multipart or presigned URL upload.

**Upload size consideration:** Lambda Function URLs accept up to 20 MB payload. Current limit is 50 MB per file. Options:
- Lower limit to 20 MB (most AIGs are under this), or
- Use S3 presigned URL for upload (browser uploads directly to S3, then notifies Lambda)

Recommendation: **presigned URL upload** — browser requests a presigned PUT URL from Lambda, uploads directly to S3, then calls classify. This removes the payload size constraint entirely and is faster for large files.

---

## Presigned URL Upload Flow

```
Browser                    Lambda                         S3
  │                          │                            │
  ├─POST /api/ingest/upload──►│                            │
  │  {filenames, sizes}      │                            │
  │                          ├─generate presigned URLs────►│
  │◄─{session_id, urls[]}────┤                            │
  │                          │                            │
  ├─PUT {presigned_url}──────┼────────────────────────────►│
  │  (file bytes)            │                            │
  │                          │                            │
  ├─POST /api/ingest/{id}/confirm─►│                      │
  │  {file_ids uploaded}     │                            │
  │◄─{files: [...]}──────────┤                            │
```

---

## Security

- Function URL: no auth (acceptable for single-user internal tool)
- S3 bucket: private, accessed only by Lambda's execution role
- No secrets in code — all via Lambda environment variables
- Optional: restrict Function URL to specific IP via Lambda resource policy (future enhancement)

---

## Cost Estimate (single user, ~100 requests/day)

| Resource | Monthly Cost |
|----------|-------------|
| Lambda compute (100 req × 500ms avg × 1024MB) | ~$0.01 |
| Lambda requests | ~$0.00 |
| S3 storage (library_db ~5 MB) | ~$0.00 |
| S3 requests (~300/day) | ~$0.01 |
| **Total** | **< $0.05/month** |

---

## Implementation Order

1. **Storage abstraction** — `StorageBackend` interface + `LocalStorageBackend` + `S3StorageBackend`
2. **Refactor services** — `LibraryDBService` and `IngestService` to use `StorageBackend`
3. **Presigned upload** — Replace direct file upload with presigned URL flow
4. **Lambda handler** — `lambda_handler.py` with Mangum
5. **Build script** — `deploy/aws/build-deploy-lambda.sh`
6. **SAM template** — `deploy/aws/sam-template.yaml`
7. **S3 bucket + initial sync** — Create bucket, upload existing library_db
8. **Deploy & test** — Deploy, verify QC editing and ingest flow end-to-end
