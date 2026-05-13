from fastapi import APIRouter, Request, Query
from typing import Optional

from ..services.audit_service import AuditService

router = APIRouter()


@router.get("/audit")
def get_audit(request: Request, limit: Optional[int] = Query(None)):
    audit = AuditService(request.app.state.db_path)
    return audit.get_entries(limit=limit)
