"""On Lambda the library lives in S3 and the code dir is read-only: mirror it into /tmp once per warm instance."""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)
_DEST = Path("/tmp/library_db_new")
_DONE = _DEST / "_sync_complete"


def resolve_library_dir() -> Path:
    """Local folder holding the library. AIGV2_LIBRARY_DB wins; on Lambda sync from S3; else library_db_new."""
    explicit = os.environ.get("AIGV2_LIBRARY_DB")
    if explicit:
        return Path(explicit)
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return _sync_from_s3()
    return Path("library_db_new")


def _sync_from_s3() -> Path:
    if _DONE.exists():
        return _DEST
    import boto3

    bucket = os.environ["LIBRARY_S3_BUCKET"]
    prefix = os.environ.get("LIBRARY_S3_PREFIX", "library_db_v2").strip("/") + "/"
    s3 = boto3.client("s3")
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", []) if not o["Key"].endswith("/")]
    if not keys:
        raise RuntimeError(f"no library files under s3://{bucket}/{prefix}")

    def fetch(key: str) -> None:
        target = _DEST / key[len(prefix):]
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(target))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(fetch, keys))  # re-raises any download failure
    _DONE.write_text(str(len(keys)))
    log.info("synced %d library files from s3://%s/%s to %s", len(keys), bucket, prefix, _DEST)
    return _DEST
