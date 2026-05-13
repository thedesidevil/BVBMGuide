from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from typing import Optional

from ..services.audit_service import AuditService

router = APIRouter()


class AuditLogRequest(BaseModel):
    category: str
    city: str
    item_name: str
    reason: str
    item_snapshot: dict
    deleted_by: str = "unknown"


@router.get("/audit")
def get_audit(request: Request, limit: Optional[int] = Query(None)):
    audit = AuditService(request.app.state.db_path)
    return audit.get_entries(limit=limit)


@router.post("/audit")
def log_audit(request: Request, body: AuditLogRequest):
    audit = AuditService(request.app.state.db_path)
    audit.log_deletion(
        category=body.category,
        city=body.city,
        item_name=body.item_name,
        reason=body.reason,
        item_snapshot=body.item_snapshot,
        deleted_by=body.deleted_by,
    )
    return {"status": "logged"}
