"""AIG verification API endpoint."""

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from docx.opc.exceptions import PackageNotFoundError

from ..services.verify_service import verify

router = APIRouter()

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCX_MAGIC = b"PK"  # DOCX is a ZIP; all ZIPs start with PK


@router.post("/verify")
async def verify_aig(request: Request, file: UploadFile = File(...)):
    """Verify an uploaded AIG DOCX against the QC checklist.

    Runs a two-layer pipeline:
      - Layer 1: deterministic rule engine (R1–R10)
      - Layer 2: GPT AI pass with structured output (A1–A20)

    Returns merged findings and narrative commentary.
    """
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are accepted")

    content = await file.read()

    if len(content) < 4 or content[:2] != _DOCX_MAGIC:
        raise HTTPException(status_code=400, detail="File does not appear to be a valid DOCX")

    try:
        result = verify(content)
    except PackageNotFoundError:
        raise HTTPException(status_code=400, detail="File appears to be a corrupted or password-protected DOCX — please re-save and try again")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")

    return result.to_dict()
