"""Ingest wizard API endpoints."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..services.ingest_service import IngestService

router = APIRouter(prefix="/ingest")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _get_service(request: Request) -> IngestService:
    from ..storage import LocalStorageBackend

    db_path = Path(request.app.state.db_path)
    library_path = Path(request.app.state.library_path)
    backend = LocalStorageBackend(db_path)
    return IngestService(backend, library_path)


class FileUpdateRequest(BaseModel):
    assigned_folder: Optional[str] = None
    excluded: Optional[bool] = None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
):
    """Create a new session and upload files to it."""
    service = _get_service(request)
    session = service.create_session()

    all_entries: list[dict] = []
    for upload in files:
        content = await upload.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload.filename!r} exceeds 50 MB limit",
            )
        entries = service.save_upload(session, upload.filename or "upload", content)
        all_entries.extend(entries)

    return {"session_id": session.session_id, "files": all_entries}


@router.post("/{session_id}/upload")
async def upload_to_session(
    session_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
):
    """Add files to an existing session."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    all_entries: list[dict] = []
    for upload in files:
        content = await upload.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload.filename!r} exceeds 50 MB limit",
            )
        entries = service.save_upload(session, upload.filename or "upload", content)
        all_entries.extend(entries)

    return {"session_id": session_id, "files": all_entries}


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------

@router.delete("/{session_id}/files/{file_id}")
def delete_file(session_id: str, file_id: str, request: Request):
    """Remove a file from a session."""
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
    """Update file metadata (assigned_folder, excluded)."""
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
        # Determine whether this is a new (not yet existing) folder
        library_path = Path(request.app.state.library_path)
        updates["is_new_folder"] = not (library_path / body.assigned_folder).exists()

    if updates:
        session.update_file(file_id, updates)

    updated_entry = session.get_file(file_id)
    return updated_entry


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

@router.post("/{session_id}/classify")
def classify(session_id: str, request: Request):
    """Run AI classification on all non-excluded files."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service.classify_all(session)
    return {"files": list(session.get_files().values())}


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

@router.post("/{session_id}/extract")
def extract(session_id: str, request: Request):
    """Run AI extraction on all classified files."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    service.extract_all(session)
    return {"status": "complete"}


@router.get("/{session_id}/extract/status")
def extract_status(session_id: str, request: Request):
    """Get per-file extraction status and data."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    status = service.get_extraction_status(session)
    return {"files": list(status.values())}


@router.put("/{session_id}/files/{file_id}/data")
def save_file_data(session_id: str, file_id: str, request: Request, body: dict):
    """Save user-edited extracted data for a file."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entry = session.get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    service.save_extracted_edits(session, file_id, body)
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------

@router.post("/{session_id}/persist")
def persist(session_id: str, request: Request):
    """Merge extracted data into the library database and clean up staging."""
    service = _get_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result = service.persist(session)
    return result if result is not None else {"status": "ok"}


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

@router.get("/folders")
def list_folders(request: Request):
    """Return existing aig-library subdirectory names."""
    library_path = Path(request.app.state.library_path)
    if not library_path.exists():
        return {"folders": []}

    folders = sorted(
        entry.name
        for entry in library_path.iterdir()
        if entry.is_dir()
    )
    return {"folders": folders}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
def ingest_history(request: Request):
    """Return all previously ingested/processed files with metadata."""
    from ..storage import LocalStorageBackend

    db_path = Path(request.app.state.db_path)
    backend = LocalStorageBackend(db_path)
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
