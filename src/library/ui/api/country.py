from fastapi import APIRouter, Request, HTTPException
from pathlib import Path

from ..services.db_service import LibraryDBService
from ..services.country_extractor import ensure_country_shards

router = APIRouter()


@router.get("/country/{name}")
def get_country(name: str, request: Request):
    db_path = Path(request.app.state.db_path)
    ensure_country_shards(db_path)
    db = LibraryDBService(request.app.state.db_path)
    data = db.get_country_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Country '{name}' not found")
    return data


@router.put("/country/{name}")
def save_country(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.db_path)
    db.save_country_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}
