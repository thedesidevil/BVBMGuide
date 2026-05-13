from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services.db_service import LibraryDBService

router = APIRouter()


class ReviewRequest(BaseModel):
    reviewed_by: str = "unknown"


@router.post("/city/{name}/review")
def review_city(name: str, request: Request, body: ReviewRequest):
    db = LibraryDBService(request.app.state.db_path)
    db.set_review_status(name, "reviewed", reviewed_by=body.reviewed_by)
    return {"status": "reviewed"}


@router.post("/country/{name}/review")
def review_country(name: str, request: Request, body: ReviewRequest):
    db = LibraryDBService(request.app.state.db_path)
    db.set_review_status(name, "reviewed", reviewed_by=body.reviewed_by)
    return {"status": "reviewed"}
