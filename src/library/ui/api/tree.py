from fastapi import APIRouter, Request

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/tree")
def get_tree(request: Request):
    db = LibraryDBService(request.app.state.db_path)
    return db.get_tree()
