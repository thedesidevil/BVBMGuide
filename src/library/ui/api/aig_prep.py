"""AIG prep API endpoint — generates library context and client profile."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

router = APIRouter()

_DOCX_MAGIC = b"PK"  # DOCX is a ZIP


@router.post("/aig/prep")
async def aig_prep(request: Request, file: UploadFile = File(...)):
    """Generate library context and client profile from an uploaded input DOCX.

    Accepts a .docx notes file or service voucher.  Returns markdown strings
    for both companion documents plus a safe filename base the UI can use when
    naming the downloads.
    """
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are accepted")

    content = await file.read()

    if len(content) < 4 or content[:2] != _DOCX_MAGIC:
        raise HTTPException(
            status_code=400,
            detail="File does not appear to be a valid DOCX",
        )

    # Resolve library DB path from app state (set by create_app)
    storage = request.app.state.storage_backend
    db_path = getattr(storage, "db_path", Path("library_db"))

    # Write DOCX to a temp file so parse_itinerary / run_prep can read it
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_docx = Path(tmpdir) / Path(file.filename or "input.docx").name
        tmp_docx.write_bytes(content)

        # Attempt to get AI client; fall back to regex if unavailable
        ai_client = None
        try:
            from src.common.ai_provider import get_ai_client
            ai_client = get_ai_client()
        except Exception:
            pass  # regex fallback is fine for prep

        try:
            from src.aig.prep import extract_trip_context, generate_library_context, generate_client_profile, _filename_base
            ctx = extract_trip_context(tmp_docx, ai_client=ai_client)

            library_md = generate_library_context(ctx, db_path)
            profile_md = generate_client_profile(ctx)
            base = _filename_base(ctx)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Prep failed: {e}")

    return {
        "library_context": library_md,
        "client_profile": profile_md,
        "filename_base": base,
    }
