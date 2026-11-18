"""AWS Lambda entry point — Mangum wraps the FastAPI app."""

import logging
import os
import time
from pathlib import Path

from mangum import Mangum

from . import create_app
from .storage import get_storage_backend

# The Lambda runtime already ships root-logger output to CloudWatch but leaves the level at WARNING,
# which hides every log.info() in the app. LOG_LEVEL=DEBUG gives more detail.
_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.getLogger().setLevel(_level)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
log = logging.getLogger("bvbm.lambda")
_COLD = True

backend = get_storage_backend()

library_path = Path(os.environ["LIBRARY_PATH"]) if os.environ.get("LIBRARY_PATH") else None

app = create_app(storage_backend=backend, library_path=library_path or Path("aig-library"))
_mangum = Mangum(app)


def handler(event, context):
    """Log one line per request (method, path, status, ms) and mark cold starts."""
    global _COLD
    cold, _COLD = _COLD, False
    http = (event.get("requestContext") or {}).get("http") or {}
    method, path = http.get("method") or event.get("httpMethod"), http.get("path") or event.get("path")
    t0 = time.monotonic()
    log.info("request start %s %s cold_start=%s request_id=%s", method, path, cold, getattr(context, "aws_request_id", "-"))
    try:
        resp = _mangum(event, context)
    except Exception:
        log.exception("request crashed %s %s after %.0f ms", method, path, (time.monotonic() - t0) * 1000)
        raise
    log.info("request end %s %s -> %s in %.0f ms", method, path, (resp or {}).get("statusCode"), (time.monotonic() - t0) * 1000)
    return resp
