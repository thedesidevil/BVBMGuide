"""On Lambda the library lives in S3 and the code dir is read-only: mirror it into /tmp.

The mirror is built once per warm instance and refreshed incrementally: at most once per
STALE_CHECK_SECONDS, one S3 listing is compared (by ETag) with what was downloaded, and only
changed files are fetched and removed ones deleted. refresh_if_stale() reports whether anything changed.
"""
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)
_DEST = Path("/tmp/library_db_new")
STALE_CHECK_SECONDS = 60
_lock = threading.Lock()
_manifest: dict[str, str] = {}  # relative path -> S3 ETag of what is on disk
_last_check = 0.0


def on_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")) and not os.environ.get("AIGV2_LIBRARY_DB")


def resolve_library_dir() -> Path:
    """Local folder holding the library. AIGV2_LIBRARY_DB wins; on Lambda sync from S3; else library_db_new."""
    explicit = os.environ.get("AIGV2_LIBRARY_DB")
    if explicit:
        return Path(explicit)
    if on_lambda():
        _sync()
        return _DEST
    return Path("library_db_new")


def refresh_if_stale(force: bool = False) -> bool:
    """Re-sync changed files from S3 (Lambda only, rate-limited). True if the local copy changed."""
    global _last_check
    if not on_lambda():
        return False
    with _lock:
        if not force and time.monotonic() - _last_check < STALE_CHECK_SECONDS:
            return False
    try:
        return _sync()
    except Exception:  # noqa: BLE001 - a failed check must not break a request; keep serving the copy we have
        log.exception("library staleness check failed; keeping the current copy")
        return False


def _sync() -> bool:
    global _last_check
    import boto3

    bucket = os.environ["LIBRARY_S3_BUCKET"]
    prefix = os.environ.get("LIBRARY_S3_PREFIX", "library_db_v2").strip("/") + "/"
    from botocore.config import Config

    s3 = boto3.client("s3", config=Config(max_pool_connections=16))
    remote: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            if not o["Key"].endswith("/"):
                remote[o["Key"][len(prefix):]] = o["ETag"]
    if not remote:
        raise RuntimeError(f"no library files under s3://{bucket}/{prefix}")
    with _lock:
        first = not _manifest
        changed = [k for k, e in remote.items() if _manifest.get(k) != e]
        removed = [k for k in _manifest if k not in remote]

        def fetch(rel: str) -> None:
            target = _DEST / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            s3.download_file(bucket, prefix + rel, str(tmp))
            os.replace(tmp, target)  # never leave a half-written file for a reader

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(fetch, changed))  # re-raises any download failure
        for rel in removed:
            (_DEST / rel).unlink(missing_ok=True)
        _manifest.clear()
        _manifest.update(remote)
        _last_check = time.monotonic()
    if changed or removed:
        log.info("library mirror: %d updated, %d removed (%s)", len(changed), len(removed),
                 "initial sync" if first else "refresh")
    return bool(changed or removed) and not first
