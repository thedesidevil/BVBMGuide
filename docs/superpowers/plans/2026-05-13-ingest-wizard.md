# Ingest Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 3-step ingest wizard (Upload → Classify → Extract & Persist) to the existing Library QC UI, allowing users to upload new AIG documents, review AI classification and extraction results, and persist approved data into the library database.

**Architecture:** New FastAPI router (`ingest.py`) handles upload, classification, extraction, and persist. Session-scoped staging in `library_db/_staging/{session_id}/`. Frontend adds an "Ingest" tab with wizard state machine. Reuses existing `LibraryIngester._classify_file` for classification and `LibraryBuilder._process_file` for extraction.

**Tech Stack:** Python 3.11+, FastAPI (multipart upload via `python-multipart`), React 19, Vite, Tailwind CSS. Existing `EditableTable` component reused for extraction preview editing.

---

## File Structure

```
src/library/ui/
  api/
    ingest.py                — All ingest API endpoints (upload, classify, extract, persist)
  services/
    ingest_service.py        — Session management, staging I/O, classification, extraction, persist logic

ui-frontend/src/
  components/
    IngestWizard.tsx          — Wizard container, step navigation, session state
    IngestUpload.tsx          — Drop zone, file list, upload handling
    IngestClassify.tsx        — Classification table with override dropdowns
    IngestExtract.tsx         — File list + editable extraction preview
  api/
    client.ts                — (modify) Add ingest API methods
  types.ts                   — (modify) Add ingest types
  App.tsx                    — (modify) Add "Ingest" mode/tab
  components/
    Layout.tsx               — (modify) Add "Ingest" tab button
```

---

## Task 1: Add python-multipart dependency and create ingest service

**Files:**
- Modify: `requirements.txt`
- Create: `src/library/ui/services/ingest_service.py`

- [ ] **Step 1: Add python-multipart to requirements.txt**

Add below the existing `uvicorn` line in `requirements.txt`:
```
python-multipart>=0.0.9
```

- [ ] **Step 2: Install the dependency**

Run: `pip install python-multipart>=0.0.9`
Expected: Successfully installed

- [ ] **Step 3: Create ingest_service.py**

```python
"""Ingest session management — staging, classification, extraction, persist."""

import json
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.common.ai_provider import get_ai_client
from src.library.builder import LibraryBuilder
from src.library.ingester import LibraryIngester


class IngestSession:
    """Manages one ingest session's staging directory and file states."""

    def __init__(self, session_id: str, staging_root: Path):
        self.session_id = session_id
        self.root = staging_root / session_id
        self.uploads_dir = self.root / "uploads"
        self.extracted_dir = self.root / "extracted"
        self.meta_path = self.root / "meta.json"
        self._meta: dict = {}

    def ensure_dirs(self):
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)

    def load_meta(self) -> dict:
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self._meta = json.load(f)
        else:
            self._meta = {
                "session_id": self.session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {},
            }
        return self._meta

    def save_meta(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self._meta, f, indent=2, ensure_ascii=False)

    def add_file(self, file_id: str, filename: str, size: int, file_type: str) -> dict:
        entry = {
            "id": file_id,
            "filename": filename,
            "size": size,
            "type": file_type,
            "state": "uploaded",
            "assigned_folder": None,
            "is_new_folder": False,
            "excluded": False,
        }
        self._meta["files"][file_id] = entry
        self.save_meta()
        return entry

    def remove_file(self, file_id: str) -> bool:
        if file_id not in self._meta["files"]:
            return False
        entry = self._meta["files"].pop(file_id)
        upload_path = self.uploads_dir / f"{file_id}{self._ext(entry)}"
        if upload_path.exists():
            upload_path.unlink()
        extracted_path = self.extracted_dir / f"{file_id}.json"
        if extracted_path.exists():
            extracted_path.unlink()
        self.save_meta()
        return True

    def get_files(self) -> list[dict]:
        return list(self._meta.get("files", {}).values())

    def get_file(self, file_id: str) -> Optional[dict]:
        return self._meta.get("files", {}).get(file_id)

    def update_file(self, file_id: str, updates: dict):
        if file_id in self._meta["files"]:
            self._meta["files"][file_id].update(updates)
            self.save_meta()

    def get_upload_path(self, file_id: str) -> Optional[Path]:
        entry = self.get_file(file_id)
        if not entry:
            return None
        return self.uploads_dir / f"{file_id}{self._ext(entry)}"

    def get_extracted_path(self, file_id: str) -> Path:
        return self.extracted_dir / f"{file_id}.json"

    def cleanup(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def _ext(self, entry: dict) -> str:
        return f".{entry['type']}"


class IngestService:
    """Orchestrates ingest operations: upload, classify, extract, persist."""

    def __init__(self, db_path: Path, library_path: Path):
        self.db_path = db_path
        self.library_path = library_path
        self.staging_root = db_path / "_staging"
        self.staging_root.mkdir(exist_ok=True)

    def create_session(self) -> IngestSession:
        session_id = str(uuid.uuid4())
        session = IngestSession(session_id, self.staging_root)
        session.ensure_dirs()
        session.load_meta()
        session.save_meta()
        return session

    def get_session(self, session_id: str) -> Optional[IngestSession]:
        session = IngestSession(session_id, self.staging_root)
        if not session.meta_path.exists():
            return None
        session.load_meta()
        return session

    def save_upload(self, session: IngestSession, filename: str, content: bytes) -> dict:
        """Save an uploaded file to staging. Returns file entry."""
        file_id = str(uuid.uuid4())
        ext = Path(filename).suffix.lower().lstrip(".")

        if ext == "zip":
            return self._handle_zip(session, filename, content)

        if ext not in ("pdf", "docx"):
            raise ValueError(f"Unsupported file type: .{ext}")

        dest = session.uploads_dir / f"{file_id}.{ext}"
        dest.write_bytes(content)
        return session.add_file(file_id, filename, len(content), ext)

    def _handle_zip(self, session: IngestSession, zip_filename: str, content: bytes) -> dict:
        """Extract zip and add each pdf/docx inside."""
        import tempfile
        tmp = Path(tempfile.mktemp(suffix=".zip"))
        tmp.write_bytes(content)
        added = []
        try:
            with zipfile.ZipFile(tmp) as zf:
                for name in zf.namelist():
                    ext = Path(name).suffix.lower().lstrip(".")
                    if ext not in ("pdf", "docx"):
                        continue
                    if name.startswith("__MACOSX") or name.startswith("."):
                        continue
                    file_id = str(uuid.uuid4())
                    inner_content = zf.read(name)
                    dest = session.uploads_dir / f"{file_id}.{ext}"
                    dest.write_bytes(inner_content)
                    entry = session.add_file(file_id, Path(name).name, len(inner_content), ext)
                    added.append(entry)
        finally:
            tmp.unlink()
        return added

    def classify_all(self, session: IngestSession) -> list[dict]:
        """Run AI classification on all uploaded (non-excluded) files."""
        existing_folders = sorted(
            f.name for f in self.library_path.iterdir() if f.is_dir()
        ) if self.library_path.exists() else []

        ingester = LibraryIngester(self.library_path)
        results = []

        for file_id, entry in session._meta["files"].items():
            if entry["excluded"] or entry["state"] == "persisted":
                continue
            upload_path = session.get_upload_path(file_id)
            if not upload_path or not upload_path.exists():
                continue

            folder = ingester._classify_file(upload_path, existing_folders)
            is_new = folder not in existing_folders if folder else False

            session.update_file(file_id, {
                "state": "classified",
                "assigned_folder": folder,
                "is_new_folder": is_new,
            })
            results.append(session.get_file(file_id))

        return results

    def extract_all(self, session: IngestSession, workers: int = 5) -> None:
        """Run AI extraction on all classified (non-excluded) files."""
        builder = LibraryBuilder(self.library_path, workers=workers)

        files_to_extract = [
            (file_id, entry)
            for file_id, entry in session._meta["files"].items()
            if entry["state"] == "classified" and not entry["excluded"]
        ]

        def extract_one(file_id: str, entry: dict):
            upload_path = session.get_upload_path(file_id)
            if not upload_path or not upload_path.exists():
                return file_id, None, "File not found"
            try:
                data = builder._process_file(upload_path)
                return file_id, data, None
            except Exception as e:
                return file_id, None, str(e)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(extract_one, fid, entry): fid
                for fid, entry in files_to_extract
            }
            for future in as_completed(futures):
                file_id, data, error = future.result()
                if data:
                    out_path = session.get_extracted_path(file_id)
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    session.update_file(file_id, {"state": "extracted"})
                else:
                    session.update_file(file_id, {
                        "state": "failed",
                        "error": error or "No data extracted",
                    })

    def get_extraction_status(self, session: IngestSession) -> list[dict]:
        """Return per-file extraction status."""
        results = []
        for file_id, entry in session._meta["files"].items():
            item = {
                "id": file_id,
                "filename": entry["filename"],
                "state": entry["state"],
                "assigned_folder": entry.get("assigned_folder"),
                "excluded": entry.get("excluded", False),
                "error": entry.get("error"),
            }
            if entry["state"] == "extracted":
                out_path = session.get_extracted_path(file_id)
                if out_path.exists():
                    with open(out_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    item["data"] = data
            results.append(item)
        return results

    def save_extracted_edits(self, session: IngestSession, file_id: str, data: dict):
        """Save user's edits to extracted data."""
        out_path = session.get_extracted_path(file_id)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def persist(self, session: IngestSession) -> dict:
        """Commit all extracted data: merge into library_db, move source files."""
        from .db_service import LibraryDBService

        db = LibraryDBService(self.db_path)
        affected_cities: set[str] = set()
        persisted_count = 0

        for file_id, entry in session._meta["files"].items():
            if entry["excluded"] or entry["state"] != "extracted":
                continue

            out_path = session.get_extracted_path(file_id)
            if not out_path.exists():
                continue

            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            folder = entry["assigned_folder"]
            covered_cities = data.get("covered_cities", [])

            # Merge items into city shards
            city_fields = ["restaurants", "attractions", "hotels", "local_dishes", "souvenirs"]
            multi_city_fields = ["safety_tips", "connectivity_tips", "health_tips",
                                 "phrases", "emergency_contacts", "transport_options"]

            for field in city_fields:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    city = (item.get("city") or folder or "").strip().title()
                    if not city:
                        continue
                    existing = db.get_city_data(city) or self._empty_city_shard()
                    if not self._is_duplicate(existing.get(field, []), item, field):
                        existing.setdefault(field, []).append(item)
                        db.save_city_data(city, existing)
                        affected_cities.add(city)

            for field in multi_city_fields:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    cities = item.get("cities") or [item.get("city") or folder or ""]
                    for city in cities:
                        city = city.strip().title()
                        if not city:
                            continue
                        existing = db.get_city_data(city) or self._empty_city_shard()
                        existing.setdefault(field, []).append(item)
                        db.save_city_data(city, existing)
                        affected_cities.add(city)

            # Move source file to aig-library/{folder}/
            upload_path = session.get_upload_path(file_id)
            if upload_path and upload_path.exists() and folder:
                dest_dir = self.library_path / folder
                dest_dir.mkdir(exist_ok=True)
                dest_file = dest_dir / entry["filename"]
                if not dest_file.exists():
                    shutil.move(str(upload_path), dest_file)

            session.update_file(file_id, {"state": "persisted"})
            persisted_count += 1

        # Reset review status for affected cities
        for city in affected_cities:
            db.set_review_status(city, "pending")

        # Cleanup staging
        session.cleanup()

        return {
            "persisted_files": persisted_count,
            "affected_cities": list(affected_cities),
        }

    def _empty_city_shard(self) -> dict:
        return {
            "restaurants": [], "attractions": [], "hotels": [],
            "local_dishes": [], "phrases": [], "safety_tips": [],
            "souvenirs": [], "emergency_contacts": [],
            "connectivity_tips": [], "transport_options": [],
            "health_tips": [], "source_files": [],
        }

    def _is_duplicate(self, existing_items: list, new_item: dict, field: str) -> bool:
        """Check if an item already exists by name (or item for souvenirs)."""
        key = "item" if field == "souvenirs" else "name"
        new_name = (new_item.get(key) or "").lower().strip()
        if not new_name:
            return False
        for item in existing_items:
            if (item.get(key) or "").lower().strip() == new_name:
                return True
        return False
```

- [ ] **Step 4: Verify import**

Run: `python -c "from src.library.ui.services.ingest_service import IngestService; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/library/ui/services/ingest_service.py
git commit -m "feat(ingest-ui): add ingest service with session management, classify, extract, persist"
```

---

## Task 2: Ingest API endpoints

**Files:**
- Create: `src/library/ui/api/ingest.py`
- Modify: `src/library/ui/__init__.py`

- [ ] **Step 1: Create ingest.py router**

```python
"""Ingest wizard API endpoints."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from ..services.ingest_service import IngestService

router = APIRouter(prefix="/ingest")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _get_service(request: Request) -> IngestService:
    db_path = Path(request.app.state.db_path)
    library_path = Path(request.app.state.library_path)
    return IngestService(db_path, library_path)


@router.post("/upload")
async def upload_files(request: Request, files: list[UploadFile] = File(...)):
    service = _get_service(request)
    session = service.create_session()
    all_entries = []

    for file in files:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(400, f"File {file.filename} exceeds 50MB limit")
        result = service.save_upload(session, file.filename or "unknown", content)
        if isinstance(result, list):
            all_entries.extend(result)
        else:
            all_entries.append(result)

    return {"session_id": session.session_id, "files": all_entries}


@router.post("/{session_id}/upload")
async def upload_more_files(session_id: str, request: Request, files: list[UploadFile] = File(...)):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    all_entries = []
    for file in files:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(400, f"File {file.filename} exceeds 50MB limit")
        result = service.save_upload(session, file.filename or "unknown", content)
        if isinstance(result, list):
            all_entries.extend(result)
        else:
            all_entries.append(result)

    return {"session_id": session_id, "files": session.get_files()}


@router.delete("/{session_id}/files/{file_id}")
def delete_file(session_id: str, file_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if not session.remove_file(file_id):
        raise HTTPException(404, "File not found")
    return {"status": "removed", "files": session.get_files()}


class FileUpdateRequest(BaseModel):
    assigned_folder: Optional[str] = None
    excluded: Optional[bool] = None


@router.put("/{session_id}/files/{file_id}")
def update_file(session_id: str, file_id: str, request: Request, body: FileUpdateRequest):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    entry = session.get_file(file_id)
    if not entry:
        raise HTTPException(404, "File not found")

    updates = {}
    if body.assigned_folder is not None:
        updates["assigned_folder"] = body.assigned_folder
        updates["state"] = "classified"
        existing_folders = sorted(
            f.name for f in service.library_path.iterdir() if f.is_dir()
        ) if service.library_path.exists() else []
        updates["is_new_folder"] = body.assigned_folder not in existing_folders
    if body.excluded is not None:
        updates["excluded"] = body.excluded

    session.update_file(file_id, updates)
    return session.get_file(file_id)


@router.post("/{session_id}/classify")
def classify_files(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    results = service.classify_all(session)
    return {"files": results}


@router.post("/{session_id}/extract")
def extract_files(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    service.extract_all(session)
    return {"status": "complete"}


@router.get("/{session_id}/extract/status")
def extraction_status(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {"files": service.get_extraction_status(session)}


@router.put("/{session_id}/files/{file_id}/data")
def save_extracted_data(session_id: str, file_id: str, request: Request, body: dict):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    service.save_extracted_edits(session, file_id, body)
    return {"status": "saved"}


@router.post("/{session_id}/persist")
def persist_session(session_id: str, request: Request):
    service = _get_service(request)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    result = service.persist(session)
    return result


@router.get("/folders")
def get_folders(request: Request):
    """Return list of existing aig-library folders for override dropdowns."""
    service = _get_service(request)
    if not service.library_path.exists():
        return {"folders": []}
    folders = sorted(f.name for f in service.library_path.iterdir() if f.is_dir())
    return {"folders": folders}
```

- [ ] **Step 2: Register ingest router and add library_path to app state**

Update `src/library/ui/__init__.py`:
```python
"""FastAPI application factory for the Library QC UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import tree, city, country, review, sweep, audit, ingest


def create_app(db_path: Path, library_path: Path = Path("aig-library")) -> FastAPI:
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

    app.state.db_path = db_path
    app.state.library_path = library_path

    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")

    # Serve built frontend if it exists (must come last so API routes take priority)
    from fastapi.staticfiles import StaticFiles

    dist_path = Path(__file__).parent.parent.parent.parent / "ui-frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    return app
```

- [ ] **Step 3: Update server.py to pass library_path**

Update `src/library/ui/server.py` to accept and forward `library_path`:
```python
import uvicorn
from pathlib import Path
from . import create_app


def run(db_path: Path, library_path: Path = Path("aig-library"), host: str = "127.0.0.1", port: int = 8765):
    app = create_app(db_path=db_path, library_path=library_path)
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 4: Update CLI ui command to pass library_path**

In `src/library/__main__.py`, update the `ui` command signature to add `--library` option and pass it through:
```python
@app.command()
def ui(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host address to bind to",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        help="Port number to listen on",
    ),
):
    """Start the Library QC web UI."""
    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}\nRun 'build' first.")
        raise typer.Exit(1)

    console.print(Panel.fit(
        "[bold blue]Library QC UI[/bold blue]\n"
        f"[dim]Serving at http://{host}:{port}[/dim]",
        border_style="blue",
    ))
    console.print(f"Open [link=http://{host}:{port}]http://{host}:{port}[/link] in your browser.\n")

    from .ui.server import run
    run(db_path=db_path, library_path=library_path, host=host, port=port)
```

- [ ] **Step 5: Verify server starts with ingest router**

Run: `python -m src.library ui --help`
Expected: Shows `--library` option alongside existing options.

Run: `python -m src.library ui &` then `curl -s http://127.0.0.1:8765/api/ingest/folders | python -m json.tool` then `kill %1`
Expected: Returns JSON with `{"folders": [...]}` listing aig-library subdirectories.

- [ ] **Step 6: Commit**

```bash
git add src/library/ui/api/ingest.py src/library/ui/__init__.py src/library/ui/server.py src/library/__main__.py
git commit -m "feat(ingest-ui): add ingest API router with upload, classify, extract, persist endpoints"
```

---

## Task 3: Frontend types and API client methods

**Files:**
- Modify: `ui-frontend/src/types.ts`
- Modify: `ui-frontend/src/api/client.ts`

- [ ] **Step 1: Add ingest types to types.ts**

Append to `ui-frontend/src/types.ts`:
```typescript
// --- Ingest types ---

export interface IngestFile {
  id: string;
  filename: string;
  size: number;
  type: "pdf" | "docx";
  state: "uploaded" | "classified" | "extracted" | "excluded" | "persisted" | "failed";
  assigned_folder: string | null;
  is_new_folder: boolean;
  excluded: boolean;
  error?: string;
  data?: Record<string, any>;
}

export interface IngestSession {
  session_id: string;
  files: IngestFile[];
}

export interface PersistResult {
  persisted_files: number;
  affected_cities: string[];
}
```

- [ ] **Step 2: Add ingest methods to api/client.ts**

Add to the `api` object in `ui-frontend/src/api/client.ts`:
```typescript
  // --- Ingest ---
  ingestUpload: async (files: File[]): Promise<{ session_id: string; files: any[] }> => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const res = await fetch(`${BASE}/ingest/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  ingestUploadMore: async (sessionId: string, files: File[]): Promise<{ session_id: string; files: any[] }> => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const res = await fetch(`${BASE}/ingest/${sessionId}/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  ingestDeleteFile: (sessionId: string, fileId: string) =>
    request<{ status: string; files: any[] }>(`/ingest/${sessionId}/files/${fileId}`, { method: "DELETE" }),
  ingestUpdateFile: (sessionId: string, fileId: string, updates: { assigned_folder?: string; excluded?: boolean }) =>
    request<any>(`/ingest/${sessionId}/files/${fileId}`, { method: "PUT", body: JSON.stringify(updates) }),
  ingestClassify: (sessionId: string) =>
    request<{ files: any[] }>(`/ingest/${sessionId}/classify`, { method: "POST" }),
  ingestExtract: (sessionId: string) =>
    request<{ status: string }>(`/ingest/${sessionId}/extract`, { method: "POST" }),
  ingestStatus: (sessionId: string) =>
    request<{ files: any[] }>(`/ingest/${sessionId}/extract/status`),
  ingestSaveData: (sessionId: string, fileId: string, data: any) =>
    request(`/ingest/${sessionId}/files/${fileId}/data`, { method: "PUT", body: JSON.stringify(data) }),
  ingestPersist: (sessionId: string) =>
    request<{ persisted_files: number; affected_cities: string[] }>(`/ingest/${sessionId}/persist`, { method: "POST" }),
  ingestFolders: () =>
    request<{ folders: string[] }>("/ingest/folders"),
```

Note: The `ingestUpload` and `ingestUploadMore` methods do NOT use the `request` helper because multipart uploads must not set `Content-Type: application/json`.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd ui-frontend && npx tsc --noEmit`
Expected: No errors (or only pre-existing unrelated ones).

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/types.ts ui-frontend/src/api/client.ts
git commit -m "feat(ingest-ui): add ingest TypeScript types and API client methods"
```

---

## Task 4: Layout update — add Ingest tab

**Files:**
- Modify: `ui-frontend/src/components/Layout.tsx`
- Modify: `ui-frontend/src/App.tsx`

- [ ] **Step 1: Update Layout to support "ingest" mode**

Change the `mode` type from `"city" | "sweep"` to `"city" | "sweep" | "ingest"` and add the Ingest button:

In `Layout.tsx`, update the `LayoutProps` interface:
```typescript
interface LayoutProps {
  mode: "city" | "sweep" | "ingest";
  onModeChange: (mode: "city" | "sweep" | "ingest") => void;
  reviewedCount: number;
  totalCount: number;
  sidebar: ReactNode;
  children: ReactNode;
}
```

Add the Ingest button after the Sweep Mode button:
```typescript
          <button
            onClick={() => onModeChange("ingest")}
            className={`px-4 py-2 rounded-md text-sm font-medium ${mode === "ingest" ? "bg-blue-50 text-blue-600" : "text-slate-500 hover:bg-slate-50"}`}
          >
            Ingest
          </button>
```

When mode is "ingest", hide the sidebar (wizard is full-width):
```typescript
      <div className="flex flex-1 overflow-hidden">
        {mode !== "ingest" && (
          <aside className="w-[260px] bg-white border-r border-slate-200 overflow-y-auto flex-shrink-0">
            {sidebar}
          </aside>
        )}
        <main className="flex-1 overflow-y-auto p-6 bg-slate-50">
          {children}
        </main>
      </div>
```

- [ ] **Step 2: Update App.tsx to render IngestWizard**

Update the mode state type and add IngestWizard rendering:
```typescript
import { IngestWizard } from "./components/IngestWizard";

// Update state type:
const [mode, setMode] = useState<"city" | "sweep" | "ingest">("city");

// Add in the render, after the sweep condition:
{mode === "ingest" && <IngestWizard onDone={() => { setMode("city"); api.getTree().then((data) => setTree(data as TreeData)); }} />}
```

- [ ] **Step 3: Create placeholder IngestWizard component**

Create `ui-frontend/src/components/IngestWizard.tsx`:
```typescript
interface IngestWizardProps {
  onDone: () => void;
}

export function IngestWizard({ onDone }: IngestWizardProps) {
  return (
    <div className="text-slate-400 text-center py-20">
      Ingest wizard placeholder — next task
    </div>
  );
}
```

- [ ] **Step 4: Verify dev server renders Ingest tab**

Run both servers. Click "Ingest" in top nav. Verify the sidebar hides and placeholder appears.

- [ ] **Step 5: Commit**

```bash
git add ui-frontend/src/components/Layout.tsx ui-frontend/src/App.tsx ui-frontend/src/components/IngestWizard.tsx
git commit -m "feat(ingest-ui): add Ingest tab to Layout with placeholder wizard"
```

---

## Task 5: IngestWizard container with step navigation

**Files:**
- Modify: `ui-frontend/src/components/IngestWizard.tsx`

- [ ] **Step 1: Implement wizard container with step state machine**

Replace `IngestWizard.tsx` with:
```typescript
import { useState } from "react";
import { IngestUpload } from "./IngestUpload";
import { IngestClassify } from "./IngestClassify";
import { IngestExtract } from "./IngestExtract";
import type { IngestFile } from "../types";

interface IngestWizardProps {
  onDone: () => void;
}

type Step = "upload" | "classify" | "extract";

const STEPS: { key: Step; label: string; number: number }[] = [
  { key: "upload", label: "Upload", number: 1 },
  { key: "classify", label: "Classify", number: 2 },
  { key: "extract", label: "Extract & Persist", number: 3 },
];

export function IngestWizard({ onDone }: IngestWizardProps) {
  const [step, setStep] = useState<Step>("upload");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [files, setFiles] = useState<IngestFile[]>([]);

  const canAdvanceToClassify = files.length > 0 && files.some((f) => !f.excluded);
  const canAdvanceToExtract = files.every(
    (f) => f.excluded || (f.state === "classified" && f.assigned_folder)
  ) && files.some((f) => !f.excluded);

  return (
    <div>
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
              step === s.key ? "bg-blue-600 text-white" :
              STEPS.findIndex((x) => x.key === step) > i ? "bg-green-500 text-white" :
              "bg-slate-200 text-slate-500"
            }`}>
              {STEPS.findIndex((x) => x.key === step) > i ? "✓" : s.number}
            </div>
            <span className={`text-sm font-medium ${step === s.key ? "text-blue-600" : "text-slate-500"}`}>
              {s.label}
            </span>
            {i < STEPS.length - 1 && <div className="w-12 h-px bg-slate-300 mx-2" />}
          </div>
        ))}
      </div>

      {/* Step content */}
      {step === "upload" && (
        <IngestUpload
          sessionId={sessionId}
          files={files}
          onSessionCreated={(sid, f) => { setSessionId(sid); setFiles(f); }}
          onFilesChanged={setFiles}
          onNext={() => setStep("classify")}
          canAdvance={canAdvanceToClassify}
        />
      )}
      {step === "classify" && sessionId && (
        <IngestClassify
          sessionId={sessionId}
          files={files}
          onFilesChanged={setFiles}
          onBack={() => setStep("upload")}
          onNext={() => setStep("extract")}
          canAdvance={canAdvanceToExtract}
        />
      )}
      {step === "extract" && sessionId && (
        <IngestExtract
          sessionId={sessionId}
          files={files}
          onFilesChanged={setFiles}
          onBack={() => setStep("classify")}
          onDone={onDone}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create placeholder IngestUpload, IngestClassify, IngestExtract**

Create `ui-frontend/src/components/IngestUpload.tsx`:
```typescript
import type { IngestFile } from "../types";

interface IngestUploadProps {
  sessionId: string | null;
  files: IngestFile[];
  onSessionCreated: (sessionId: string, files: IngestFile[]) => void;
  onFilesChanged: (files: IngestFile[]) => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestUpload({ onNext, canAdvance }: IngestUploadProps) {
  return (
    <div>
      <p className="text-slate-400">Upload step — next task</p>
      <button onClick={onNext} disabled={!canAdvance} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-40">
        Proceed to Classify
      </button>
    </div>
  );
}
```

Create `ui-frontend/src/components/IngestClassify.tsx`:
```typescript
import type { IngestFile } from "../types";

interface IngestClassifyProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestClassify({ onBack, onNext, canAdvance }: IngestClassifyProps) {
  return (
    <div>
      <p className="text-slate-400">Classify step — next task</p>
      <div className="flex gap-3 mt-4">
        <button onClick={onBack} className="px-4 py-2 border border-slate-200 rounded">Back</button>
        <button onClick={onNext} disabled={!canAdvance} className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-40">
          Proceed to Extract
        </button>
      </div>
    </div>
  );
}
```

Create `ui-frontend/src/components/IngestExtract.tsx`:
```typescript
import type { IngestFile } from "../types";

interface IngestExtractProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onDone: () => void;
}

export function IngestExtract({ onBack, onDone }: IngestExtractProps) {
  return (
    <div>
      <p className="text-slate-400">Extract & Persist step — next task</p>
      <div className="flex gap-3 mt-4">
        <button onClick={onBack} className="px-4 py-2 border border-slate-200 rounded">Back</button>
        <button onClick={onDone} className="px-4 py-2 bg-emerald-600 text-white rounded">Done</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify wizard renders with step navigation**

Run both servers. Click Ingest. Verify step indicator appears with numbered steps. Verify clicking steps doesn't crash (button is disabled until files exist).

- [ ] **Step 4: Commit**

```bash
git add ui-frontend/src/components/IngestWizard.tsx ui-frontend/src/components/IngestUpload.tsx ui-frontend/src/components/IngestClassify.tsx ui-frontend/src/components/IngestExtract.tsx
git commit -m "feat(ingest-ui): add wizard container with step navigation and placeholder steps"
```

---

## Task 6: Upload step — drop zone and file list

**Files:**
- Modify: `ui-frontend/src/components/IngestUpload.tsx`

- [ ] **Step 1: Implement full upload component**

Replace `IngestUpload.tsx`:
```typescript
import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import type { IngestFile } from "../types";

interface IngestUploadProps {
  sessionId: string | null;
  files: IngestFile[];
  onSessionCreated: (sessionId: string, files: IngestFile[]) => void;
  onFilesChanged: (files: IngestFile[]) => void;
  onNext: () => void;
  canAdvance: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function IngestUpload({ sessionId, files, onSessionCreated, onFilesChanged, onNext, canAdvance }: IngestUploadProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(async (fileList: FileList | File[]) => {
    const validFiles = Array.from(fileList).filter((f) => {
      const ext = f.name.split(".").pop()?.toLowerCase();
      return ext === "pdf" || ext === "docx" || ext === "zip";
    });
    if (validFiles.length === 0) return;

    setUploading(true);
    try {
      if (!sessionId) {
        const result = await api.ingestUpload(validFiles);
        onSessionCreated(result.session_id, result.files as IngestFile[]);
      } else {
        const result = await api.ingestUploadMore(sessionId, validFiles);
        onFilesChanged(result.files as IngestFile[]);
      }
    } catch (e: any) {
      alert(`Upload failed: ${e.message}`);
    } finally {
      setUploading(false);
    }
  }, [sessionId, onSessionCreated, onFilesChanged]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleRemove = async (fileId: string) => {
    if (!sessionId) return;
    const result = await api.ingestDeleteFile(sessionId, fileId);
    onFilesChanged(result.files as IngestFile[]);
  };

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-4">Upload Documents</h2>
      <p className="text-sm text-slate-500 mb-6">
        Upload AIG documents (PDF, DOCX, or ZIP) to add to the library. ZIP files will be extracted automatically.
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
          dragging ? "border-blue-400 bg-blue-50" : "border-slate-300 hover:border-slate-400 hover:bg-slate-50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.zip"
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
        <div className="text-4xl mb-3 text-slate-300">&#128194;</div>
        <p className="text-sm font-medium text-slate-600">
          {uploading ? "Uploading..." : "Drop files here or click to browse"}
        </p>
        <p className="text-xs text-slate-400 mt-1">PDF, DOCX, or ZIP — max 50MB per file</p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">{files.length} file(s) ready</h3>
          <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
            {files.map((file) => (
              <div key={file.id} className="flex items-center gap-3 px-4 py-3">
                <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded ${
                  file.type === "pdf" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"
                }`}>{file.type}</span>
                <span className="flex-1 text-sm text-slate-700 truncate">{file.filename}</span>
                <span className="text-xs text-slate-400">{formatSize(file.size)}</span>
                <button
                  onClick={() => handleRemove(file.id)}
                  className="text-red-400 hover:text-red-600 text-sm px-2 py-1 rounded hover:bg-red-50"
                >Remove</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Next button */}
      <div className="flex justify-end mt-8">
        <button
          onClick={onNext}
          disabled={!canAdvance}
          className="px-6 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Proceed to Classify →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test upload flow end-to-end**

Run both servers. Navigate to Ingest tab. Drop or browse a PDF. Verify it appears in the file list with correct name, size, and type badge. Verify Remove button works. Verify "Proceed to Classify" enables after a file is added.

- [ ] **Step 3: Commit**

```bash
git add ui-frontend/src/components/IngestUpload.tsx
git commit -m "feat(ingest-ui): implement upload step with drop zone and file list"
```

---

## Task 7: Classify step — AI classification with override

**Files:**
- Modify: `ui-frontend/src/components/IngestClassify.tsx`

- [ ] **Step 1: Implement full classify component**

Replace `IngestClassify.tsx`:
```typescript
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { IngestFile } from "../types";

interface IngestClassifyProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onNext: () => void;
  canAdvance: boolean;
}

export function IngestClassify({ sessionId, files, onFilesChanged, onBack, onNext, canAdvance }: IngestClassifyProps) {
  const [folders, setFolders] = useState<string[]>([]);
  const [classifying, setClassifying] = useState(false);
  const [newFolderInput, setNewFolderInput] = useState<Record<string, string>>({});

  useEffect(() => {
    api.ingestFolders().then((r) => setFolders(r.folders));
  }, []);

  const handleClassifyAll = async () => {
    setClassifying(true);
    try {
      const result = await api.ingestClassify(sessionId);
      onFilesChanged(result.files as IngestFile[]);
    } finally {
      setClassifying(false);
    }
  };

  const handleOverride = async (fileId: string, folder: string) => {
    if (folder === "__new__") return;
    await api.ingestUpdateFile(sessionId, fileId, { assigned_folder: folder });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, assigned_folder: folder, state: "classified" as const, is_new_folder: !folders.includes(folder) } : f));
  };

  const handleNewFolder = async (fileId: string) => {
    const folder = newFolderInput[fileId]?.trim();
    if (!folder) return;
    await api.ingestUpdateFile(sessionId, fileId, { assigned_folder: folder });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, assigned_folder: folder, state: "classified" as const, is_new_folder: true } : f));
    if (!folders.includes(folder)) setFolders([...folders, folder].sort());
    setNewFolderInput((prev) => ({ ...prev, [fileId]: "" }));
  };

  const handleExclude = async (fileId: string, excluded: boolean) => {
    await api.ingestUpdateFile(sessionId, fileId, { excluded });
    onFilesChanged(files.map((f) => f.id === fileId ? { ...f, excluded } : f));
  };

  const activeFiles = files.filter((f) => f.state !== "persisted");

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-2">Classify Documents</h2>
      <p className="text-sm text-slate-500 mb-6">
        AI will suggest which library folder each file belongs in. You can override the suggestion or exclude files.
      </p>

      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={handleClassifyAll}
          disabled={classifying}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-60"
        >
          {classifying ? "Classifying..." : "Classify All"}
        </button>
        {classifying && <span className="text-sm text-slate-400">Running AI classification on all files...</span>}
      </div>

      {/* Classification table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Filename</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">AI Suggestion</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Confidence</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Assigned Folder</th>
              <th className="text-center px-4 py-3 text-xs font-semibold text-slate-500 uppercase">Exclude</th>
            </tr>
          </thead>
          <tbody>
            {activeFiles.map((file) => {
              const isOverridden = file.assigned_folder && file.assigned_folder !== file.assigned_folder;
              return (
                <tr
                  key={file.id}
                  className={`border-b border-slate-100 ${file.excluded ? "opacity-50 bg-slate-50" : ""}`}
                >
                  <td className="px-4 py-3 font-medium text-slate-700">{file.filename}</td>
                  <td className="px-4 py-3">
                    {file.assigned_folder ? (
                      <span className="text-xs font-medium bg-blue-100 text-blue-700 px-2 py-1 rounded-full">
                        {file.assigned_folder}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400 italic">Not classified</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {file.state === "classified" && (
                      <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                        file.is_new_folder ? "text-red-600" : "text-green-600"
                      }`}>
                        <span className={`w-2 h-2 rounded-full ${file.is_new_folder ? "bg-red-500" : "bg-green-500"}`} />
                        {file.is_new_folder ? "Low" : "High"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {!file.excluded && (
                      <div className="flex items-center gap-2">
                        <select
                          value={file.assigned_folder || ""}
                          onChange={(e) => handleOverride(file.id, e.target.value)}
                          className="text-sm border border-slate-200 rounded-md px-2 py-1.5 max-w-[200px]"
                        >
                          <option value="">Select folder...</option>
                          {folders.map((f) => <option key={f} value={f}>{f}</option>)}
                          <option value="__new__">+ New folder...</option>
                        </select>
                        {/* Show new folder input if __new__ selected or no match */}
                        {(!file.assigned_folder || !folders.includes(file.assigned_folder)) && file.state === "uploaded" && (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              placeholder="Folder name"
                              value={newFolderInput[file.id] || ""}
                              onChange={(e) => setNewFolderInput((prev) => ({ ...prev, [file.id]: e.target.value }))}
                              className="text-sm border border-slate-200 rounded px-2 py-1 w-32"
                            />
                            <button
                              onClick={() => handleNewFolder(file.id)}
                              className="text-xs text-blue-600 font-medium hover:underline"
                            >Set</button>
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <input
                      type="checkbox"
                      checked={file.excluded}
                      onChange={(e) => handleExclude(file.id, e.target.checked)}
                      className="w-4 h-4 accent-slate-500"
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Navigation */}
      <div className="flex justify-between mt-8">
        <button onClick={onBack} className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50">
          ← Back to Upload
        </button>
        <button
          onClick={onNext}
          disabled={!canAdvance}
          className="px-6 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Proceed to Extract →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test classify flow**

Run both servers. Upload a file, proceed to classify, click "Classify All". Verify AI classification populates the suggestion column with a folder name and confidence indicator. Verify override dropdown works.

- [ ] **Step 3: Commit**

```bash
git add ui-frontend/src/components/IngestClassify.tsx
git commit -m "feat(ingest-ui): implement classify step with AI suggestions and manual override"
```

---

## Task 8: Extract & Persist step — extraction preview with editable tables

**Files:**
- Modify: `ui-frontend/src/components/IngestExtract.tsx`

- [ ] **Step 1: Implement full extract component**

Replace `IngestExtract.tsx`:
```typescript
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { EditableTable } from "./EditableTable";
import type { IngestFile } from "../types";

interface IngestExtractProps {
  sessionId: string;
  files: IngestFile[];
  onFilesChanged: (files: IngestFile[]) => void;
  onBack: () => void;
  onDone: () => void;
}

const CATEGORIES = [
  { key: "restaurants", label: "Restaurants" },
  { key: "attractions", label: "Attractions" },
  { key: "hotels", label: "Hotels" },
  { key: "local_dishes", label: "Local Dishes" },
  { key: "souvenirs", label: "Souvenirs" },
  { key: "phrases", label: "Phrases" },
  { key: "safety_tips", label: "Safety Tips" },
  { key: "connectivity_tips", label: "Connectivity" },
  { key: "transport_options", label: "Transport" },
  { key: "health_tips", label: "Health" },
  { key: "emergency_contacts", label: "Emergency" },
];

const RESTAURANT_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "cuisine_type", label: "Cuisine", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "price_range", label: "Price", type: "text" as const },
  { key: "vegetarian_friendly", label: "Veg", type: "checkbox" as const },
];

const ATTRACTION_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "description", label: "Description", type: "text" as const },
  { key: "hours", label: "Hours", type: "text" as const },
  { key: "entry_fee", label: "Fee", type: "text" as const },
];

const GENERIC_COLUMNS = [
  { key: "name", label: "Name", type: "text" as const },
  { key: "description", label: "Description", type: "text" as const },
];

const TIP_COLUMNS = [
  { key: "tip", label: "Tip", type: "text" as const },
];

const PHRASE_COLUMNS = [
  { key: "english", label: "English", type: "text" as const },
  { key: "local", label: "Local", type: "text" as const },
];

function getColumnsForCategory(cat: string) {
  if (cat === "restaurants") return RESTAURANT_COLUMNS;
  if (cat === "attractions") return ATTRACTION_COLUMNS;
  if (cat === "phrases") return PHRASE_COLUMNS;
  if (["safety_tips", "connectivity_tips", "health_tips"].includes(cat)) return TIP_COLUMNS;
  return GENERIC_COLUMNS;
}

export function IngestExtract({ sessionId, files, onFilesChanged, onBack, onDone }: IngestExtractProps) {
  const [extracting, setExtracting] = useState(false);
  const [extracted, setExtracted] = useState(false);
  const [fileStatuses, setFileStatuses] = useState<any[]>([]);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("restaurants");
  const [persisting, setPersisting] = useState(false);
  const [persistResult, setPersistResult] = useState<{ persisted_files: number; affected_cities: string[] } | null>(null);

  const handleExtract = async () => {
    setExtracting(true);
    try {
      await api.ingestExtract(sessionId);
      const status = await api.ingestStatus(sessionId);
      setFileStatuses(status.files);
      setExtracted(true);
      const firstExtracted = status.files.find((f: any) => f.state === "extracted");
      if (firstExtracted) setSelectedFileId(firstExtracted.id);
    } finally {
      setExtracting(false);
    }
  };

  const handlePersist = async () => {
    setPersisting(true);
    try {
      const result = await api.ingestPersist(sessionId);
      setPersistResult(result);
    } finally {
      setPersisting(false);
    }
  };

  const selectedFile = fileStatuses.find((f) => f.id === selectedFileId);
  const selectedData = selectedFile?.data;

  const handleDataChange = async (category: string, newItems: any[]) => {
    if (!selectedFile || !selectedData) return;
    const updatedData = { ...selectedData, [category]: newItems };
    await api.ingestSaveData(sessionId, selectedFile.id, updatedData);
    setFileStatuses((prev) =>
      prev.map((f) => f.id === selectedFile.id ? { ...f, data: updatedData } : f)
    );
  };

  // Summary stats
  const extractedFiles = fileStatuses.filter((f) => f.state === "extracted");
  const totalRestaurants = extractedFiles.reduce((s, f) => s + (f.data?.restaurants?.length || 0), 0);
  const totalAttractions = extractedFiles.reduce((s, f) => s + (f.data?.attractions?.length || 0), 0);

  if (persistResult) {
    return (
      <div className="text-center py-16">
        <div className="text-5xl mb-4">&#9989;</div>
        <h2 className="text-xl font-bold text-slate-900 mb-2">Ingest Complete</h2>
        <p className="text-sm text-slate-500 mb-6">
          {persistResult.persisted_files} file(s) processed. Data merged into {persistResult.affected_cities.length} city shard(s).
        </p>
        <div className="flex flex-wrap gap-2 justify-center mb-8">
          {persistResult.affected_cities.map((city) => (
            <span key={city} className="text-xs font-medium bg-green-100 text-green-700 px-3 py-1 rounded-full">{city}</span>
          ))}
        </div>
        <button onClick={onDone} className="px-6 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700">
          Return to Library
        </button>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-2">Extract & Persist</h2>
      <p className="text-sm text-slate-500 mb-6">
        AI extracts structured data from each document. Review and edit before persisting to the library.
      </p>

      {!extracted && (
        <div className="text-center py-12">
          <button
            onClick={handleExtract}
            disabled={extracting}
            className="px-6 py-3 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-60"
          >
            {extracting ? "Extracting... (this may take a minute)" : "Start Extraction"}
          </button>
        </div>
      )}

      {extracted && (
        <div className="flex gap-6">
          {/* Left: file list */}
          <div className="w-64 flex-shrink-0">
            <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
              {fileStatuses.map((f) => (
                <button
                  key={f.id}
                  onClick={() => f.state === "extracted" && setSelectedFileId(f.id)}
                  className={`w-full px-3 py-2.5 text-left text-sm flex items-center gap-2 ${
                    selectedFileId === f.id ? "bg-blue-50 text-blue-700 font-medium" : "text-slate-700 hover:bg-slate-50"
                  } ${f.excluded ? "opacity-40" : ""}`}
                >
                  {f.state === "extracted" && <span className="text-green-500">&#10003;</span>}
                  {f.state === "failed" && <span className="text-red-500">&#10007;</span>}
                  {f.excluded && <span className="text-slate-400">&#8212;</span>}
                  <span className="truncate">{f.filename}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Right: extracted data preview */}
          <div className="flex-1 min-w-0">
            {selectedData ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-sm font-semibold text-slate-700">{selectedFile.filename}</span>
                  {selectedFile.assigned_folder && (
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">→ {selectedFile.assigned_folder}</span>
                  )}
                </div>

                {/* Category tabs */}
                <div className="flex flex-wrap gap-1 border-b border-slate-200 mb-4">
                  {CATEGORIES.filter((cat) => (selectedData[cat.key]?.length || 0) > 0).map((cat) => (
                    <button
                      key={cat.key}
                      onClick={() => setActiveTab(cat.key)}
                      className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px ${
                        activeTab === cat.key ? "text-blue-600 border-blue-600" : "text-slate-500 border-transparent"
                      }`}
                    >
                      {cat.label} ({selectedData[cat.key]?.length || 0})
                    </button>
                  ))}
                </div>

                {/* Editable table */}
                <div className="bg-white border border-slate-200 rounded-lg p-3 max-h-[500px] overflow-auto">
                  <EditableTable
                    columns={getColumnsForCategory(activeTab)}
                    data={selectedData[activeTab] || []}
                    onDataChange={(newData) => handleDataChange(activeTab, newData)}
                    onDelete={() => {}}
                  />
                </div>
              </>
            ) : (
              <div className="text-slate-400 text-center py-12">Select a file to preview extracted data</div>
            )}
          </div>
        </div>
      )}

      {/* Bottom bar */}
      <div className="flex items-center justify-between mt-8 pt-6 border-t border-slate-200">
        <button onClick={onBack} className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50">
          ← Back to Classify
        </button>

        {extracted && (
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-500">
              {extractedFiles.length} file(s) ready — {totalRestaurants} restaurants, {totalAttractions} attractions
            </span>
            <button
              onClick={handlePersist}
              disabled={persisting || extractedFiles.length === 0}
              className="px-6 py-2.5 text-sm font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700 disabled:opacity-40"
            >
              {persisting ? "Persisting..." : "Persist All"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test full extract & persist flow**

Run both servers. Upload a small PDF guide, classify, extract. Verify extracted data appears in editable tables. Click "Persist All". Verify success screen appears with affected cities.

- [ ] **Step 3: Commit**

```bash
git add ui-frontend/src/components/IngestExtract.tsx
git commit -m "feat(ingest-ui): implement extract step with editable preview and persist"
```

---

## Task 9: End-to-end integration test

**Files:** No new files — manual verification.

- [ ] **Step 1: Start both servers**

Terminal 1: `python -m src.library ui`
Terminal 2: `cd ui-frontend && npm run dev`

- [ ] **Step 2: Verify Ingest tab appears in nav**

Open browser at Vite dev URL. Confirm "Ingest" button appears next to "Sweep Mode" in top nav.

- [ ] **Step 3: Test full happy path**

1. Click Ingest → drop zone appears, sidebar hidden
2. Upload a PDF from `input/` folder
3. File appears in list with size and type badge
4. Click "Proceed to Classify" → step 2 loads
5. Click "Classify All" → AI populates suggestions with confidence dots
6. Click "Proceed to Extract" → step 3 loads
7. Click "Start Extraction" → extraction runs, file list shows checkmarks
8. Click a file → editable table shows restaurants/attractions
9. Edit a field → verify change persists (switch files and back)
10. Click "Persist All" → success screen shows affected cities
11. Click "Return to Library" → back to City View, tree refreshed

- [ ] **Step 4: Test edge cases**

- Upload a ZIP containing mixed PDF/DOCX → verify all inner files extracted
- Exclude a file before classify → verify it's skipped
- Override a folder assignment → verify confidence changes to reflect override
- Upload a very small/empty file → verify extraction handles failure gracefully

- [ ] **Step 5: Build production frontend**

Run: `cd ui-frontend && npm run build`
Verify: `python -m src.library ui` serves the built app at http://127.0.0.1:8765 with all ingest functionality working.

- [ ] **Step 6: Commit any fixes discovered during testing**

```bash
git add -A
git commit -m "fix(ingest-ui): integration test fixes"
```

---

## Verification

After all tasks complete:

1. `python -m src.library ui` → server starts at http://127.0.0.1:8765
2. "Ingest" tab visible in top navigation
3. Upload step: drag/drop works, file list shows entries, Remove works
4. Classify step: "Classify All" calls AI, results show with confidence dots, override dropdown works, exclude checkbox works
5. Extract step: "Start Extraction" processes files, editable preview shows data in tabbed tables, "Persist All" merges into library_db and moves source files
6. After persist: affected city shards contain new data, review status reset to pending, staging cleaned up
7. No regressions: City View, Country View, Sweep Mode all still functional
