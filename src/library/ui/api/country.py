from fastapi import APIRouter, Request, HTTPException

from ..services.db_service import LibraryDBService

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
    db.save_country_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}
