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


def _run_aigv2_job(job_id: str, cold: bool) -> dict:
    """Worker invocation: run one AIG v2 job (started by jobs.submit via an async self-invoke)."""
    from src.aigv2 import jobs, pipeline
    from src.aigv2.library_sync import refresh_if_stale

    t0 = time.monotonic()
    log.info("worker start job=%s cold_start=%s", job_id, cold)
    try:
        refresh_if_stale()
        jobs.run_worker(job_id, pipeline.default_deps())
    except Exception:
        log.exception("worker crashed job=%s", job_id)
        raise
    log.info("worker end job=%s in %.1f s", job_id, time.monotonic() - t0)
    return {"job": job_id}


def handler(event, context):
    """Log one line per request (method, path, status, ms) and mark cold starts."""
    global _COLD
    cold, _COLD = _COLD, False
    if isinstance(event, dict) and event.get("aigv2_job"):
        return _run_aigv2_job(str(event["aigv2_job"]), cold)
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
