from __future__ import annotations
import json
import os

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from src.hotel_options.codes import CodeStore
from src.library.ui.services.hotel_options_service import parse_file, generate_doc

router = APIRouter()

_XLSX_MAGIC = b"PK"


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY not configured")
    return key


@router.post("/hotel-options/parse")
async def parse_hotel_options(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")
    content = await file.read()
    if len(content) < 2 or content[:2] != _XLSX_MAGIC:
        raise HTTPException(status_code=400, detail="File does not appear to be a valid Excel file")
    api_key = _api_key()
    try:
        return parse_file(content, file.filename, request.app.state.storage_backend, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")


@router.post("/hotel-options/generate")
async def generate_hotel_options(
    request: Request,
    file: UploadFile = File(...),
    resolved_codes: str = Form(default="{}"),
    overrides: str = Form(default="{}"),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")
    content = await file.read()
    try:
        codes_dict = json.loads(resolved_codes)
        overrides_dict = json.loads(overrides)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in form fields: {e}")
    api_key = _api_key()
    try:
        docx_bytes = generate_doc(
            content, file.filename, codes_dict, overrides_dict,
            request.app.state.storage_backend, api_key,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=hotel_options.docx"},
    )


@router.post("/hotel-options/codes")
async def save_hotel_code(request: Request, payload: dict):
    code = str(payload.get("code", "")).strip()
    meaning = str(payload.get("meaning", "")).strip()
    if not code or not meaning:
        raise HTTPException(status_code=400, detail="code and meaning are required")
    store = CodeStore(request.app.state.storage_backend)
    codes = store.load()
    codes[code.lower()] = meaning
    store.save(codes)
    return {"ok": True}
