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
