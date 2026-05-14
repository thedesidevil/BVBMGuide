from fastapi import APIRouter, Request

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/tree")
def get_tree(request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    return db.get_tree()
