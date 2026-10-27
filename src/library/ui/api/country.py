from fastapi import APIRouter, Request, HTTPException

from ..services.db_service import LibraryDBService
from .manual import stamp_manual_edits

router = APIRouter()


@router.get("/country/{name}")
def get_country(name: str, request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_country_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Country '{name}' not found")
    return data


@router.put("/country/{name}")
def save_country(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.storage_backend)
    existing = db.get_country_data(name) or {}
    changed_by = body.pop("changed_by", "unknown")
    stamp_manual_edits(existing, body, changed_by)
    db.save_country_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}
