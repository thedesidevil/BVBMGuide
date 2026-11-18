"""AIG v2 background jobs.

One body of job logic (`execute`) runs in two places:
  * locally, in a thread of the web process (state lives in the API module's in-memory dict);
  * on Lambda, in a separate asynchronous invocation of the same function. The browser's request only records the
    job in S3 and fires that invocation, so the work keeps running whether or not anyone is polling, and any
    instance can answer a status poll (a Lambda that has returned its response is frozen, and instances do not
    share memory or /tmp).

Lambda-side state, all under the AIG v2 storage backend:
  jobs/<id>.json          the job record the page polls (status, result, error, questions, cost)
  jobs/<id>.spec.json     what to run (kind, run id, answers, ...)
  jobs/<id>/inputs/<name> uploaded files, copied to the worker's /tmp
  jobs/<id>.cancel        cancel flag, checked before every paid call
  jobs/_active.json       the single-job lock (one job at a time: CostMeter diffs shared counters)
"""
import json
import logging
import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Optional

from src.aigv2 import cancel, pipeline
from src.aigv2.preflight import PreflightStop
from src.aigv2.store import RunStore

log = logging.getLogger(__name__)

ACTIVE_KEY = "jobs/_active.json"
MAX_RUN_SECONDS = 960      # Lambda's hard limit is 900 s; past this a "running" job is dead
MAX_QUEUE_SECONDS = 120    # an async invoke normally starts in milliseconds


def remote_enabled() -> bool:
    """True on Lambda (jobs run as separate invocations). AIGV2_LOCAL_JOBS=1 forces in-process threads."""
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")) and not os.environ.get("AIGV2_LOCAL_JOBS")


def new_job(kind: str, run_id: Optional[str]) -> dict:
    return {"id": secrets.token_hex(4), "kind": kind, "run_id": run_id, "status": "queued", "result": None,
            "error": None, "questions": [], "cost": None, "started_at": datetime.now(timezone.utc).isoformat()}


def _age(job: dict) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(job["started_at"])).total_seconds()
    except (KeyError, ValueError):
        return 0.0


def _active(job: dict) -> bool:
    return job.get("status") in ("queued", "running")


class JobStore:
    """Job records in the storage backend (S3 on Lambda)."""

    def __init__(self, backend):
        self.backend = backend

    @staticmethod
    def _key(job_id: str) -> str:
        return f"jobs/{job_id}.json"

    def save(self, job: dict) -> None:
        self.backend.write_json(self._key(job["id"]), job)

    def get_raw(self, job_id: str) -> Optional[dict]:
        if not job_id.isalnum():
            return None
        return self.backend.read_json(self._key(job_id))

    def get(self, job_id: str) -> Optional[dict]:
        """The job as the page should see it: a job that outlived Lambda's limits is reported as failed."""
        job = self.get_raw(job_id)
        if job is None or not _active(job):
            return job
        age = _age(job)
        if (job["status"] == "queued" and age > MAX_QUEUE_SECONDS) or age > MAX_RUN_SECONDS:
            job["status"] = "error"
            job["error"] = ("The job never started (the worker invocation was not picked up)" if job["status"] == "queued"
                            else "The job timed out: Lambda stopped it at its 15 minute limit. "
                                 "Work done so far is saved; start the step again.")
            log.error("job %s (%s) marked failed: stuck in %s for %.0f s", job["id"], job["kind"], job["status"], age)
            self.save(job)
            self.release(job["id"])
        return job

    def active(self) -> Optional[dict]:
        """The job holding the single-job lock, if it is still alive."""
        ptr = self.backend.read_json(ACTIVE_KEY)
        if not ptr or not ptr.get("job_id"):
            return None
        job = self.get(ptr["job_id"])
        return job if job is not None and _active(job) else None

    def acquire(self, job: dict) -> None:
        self.backend.write_json(ACTIVE_KEY, {"job_id": job["id"], "at": job["started_at"]})

    def release(self, job_id: str) -> None:
        ptr = self.backend.read_json(ACTIVE_KEY)
        if ptr and ptr.get("job_id") == job_id:
            self.backend.delete(ACTIVE_KEY)

    def request_cancel(self, job_id: str) -> None:
        self.backend.write_json(f"jobs/{job_id}.cancel", {"at": datetime.now(timezone.utc).isoformat()})

    def cancel_requested(self, job_id: str) -> bool:
        return self.backend.exists(f"jobs/{job_id}.cancel")


def _body(kind: str, run_id: Optional[str], spec: dict, deps, job: dict, intake_path: Optional[Path],
          paths: list[Path]) -> dict:
    """The work itself; returns the dict stored as job['result']."""
    if kind == "start":
        store, questions = pipeline.start_run(intake_path, paths, deps)
        job["run_id"] = store.run_id
        return {"run_id": store.run_id, "questions": len(questions)}
    store = RunStore(deps.backend, run_id)
    if kind == "plan":
        items = pipeline.plan_run(store, spec.get("answers") or {}, deps)
        job["questions"] = [q.model_dump(mode="json") for q in items]
        return {"run_id": run_id, "items": len(items)}
    if kind == "build":
        r = pipeline.build_run(store, spec.get("answers") or {}, deps)
        return {"docx_name": r.docx_name, "passed": r.qc.passed}
    if kind == "regenerate":
        r = pipeline.regenerate(store, spec.get("days") or [], spec.get("sections") or [], deps)
        return {"docx_name": r.docx_name, "passed": r.qc.passed}
    if kind == "qc":
        _, result, _ = pipeline.requalify(store, paths[0], deps)
        names = [n for n in store.names() if n.startswith("requalify/")]
        return {"passed": result.passed, "findings": len(result.findings), "files": names}
    raise ValueError(f"unknown job kind {kind!r}")


def execute(job: dict, spec: dict, deps, intake_path: Optional[Path] = None, paths: Optional[list[Path]] = None) -> None:
    """Run the job and record the outcome on `job`. Never raises (cancellation and errors become job fields)."""
    kind, run_id, t0 = job["kind"], job["run_id"], monotonic()
    job["status"] = "running"
    log.info("job %s (%s) started run_id=%s", job["id"], kind, run_id)
    try:
        job["result"] = _body(kind, run_id, spec, deps, job, intake_path, list(paths or []))
        job["status"] = "done"
        log.info("job %s (%s) done in %.1f s run_id=%s result=%s", job["id"], kind, monotonic() - t0,
                 job["run_id"], job["result"])
    except cancel.RunCancelled as e:
        log.warning("job %s (%s) cancelled after %.1f s", job["id"], kind, monotonic() - t0)
        job["status"], job["error"] = "cancelled", "Run was cancelled"
        job["run_id"] = getattr(e, "run_id", job["run_id"])
        job["cost"] = getattr(e, "run_cost", None)
    except pipeline.UnansweredQuestions as e:
        log.warning("job %s (%s) stopped: %d unanswered question(s)", job["id"], kind, len(e.questions))
        job["status"], job["error"] = "error", "Some pre-flight questions still need an answer"
        job["questions"] = [q.model_dump(mode="json") for q in e.questions]
    except Exception as e:  # surface every failure to the page, with the partial cost
        job["status"] = "error"
        job["error"] = str(e) if isinstance(e, (PreflightStop, ValueError)) else f"{type(e).__name__}: {e}"
        job["run_id"] = getattr(e, "run_id", job["run_id"])
        job["cost"] = getattr(e, "run_cost", None)
        if isinstance(e, (PreflightStop, ValueError)):
            log.warning("job %s (%s) stopped after %.1f s: %s", job["id"], kind, monotonic() - t0, e)
        else:
            log.exception("job %s (%s) failed after %.1f s", job["id"], kind, monotonic() - t0)


# ---- Lambda side -----------------------------------------------------------------------------------------------

def submit(deps, kind: str, run_id: Optional[str], spec: dict, intake_path: Optional[Path] = None,
           paths: Optional[list[Path]] = None) -> Optional[dict]:
    """Record a job in S3 and start the worker invocation. Returns None if another job holds the lock."""
    js = JobStore(deps.backend)
    if js.active() is not None:
        return None
    job = new_job(kind, run_id)
    spec = dict(spec)
    spec["intake"] = intake_path.name if intake_path else None
    spec["inputs"] = [p.name for p in (paths or [])]
    for p in ([intake_path] if intake_path else []) + list(paths or []):
        deps.backend.write_bytes(f"jobs/{job['id']}/inputs/{p.name}", p.read_bytes())
    deps.backend.write_json(f"jobs/{job['id']}.spec.json", spec)
    js.save(job)
    js.acquire(job)
    log.info("job queued kind=%s run_id=%s id=%s", kind, run_id, job["id"])
    try:
        invoke_worker(job["id"])
    except Exception as e:  # the worker will never run: do not leave the lock held
        job["status"], job["error"] = "error", f"Could not start the worker: {type(e).__name__}: {e}"
        js.save(job)
        js.release(job["id"])
        log.exception("could not invoke the worker for job %s", job["id"])
    return job


def invoke_worker(job_id: str) -> None:
    import boto3

    boto3.client("lambda").invoke(FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"], InvocationType="Event",
                                  Payload=json.dumps({"aigv2_job": job_id}).encode("utf-8"))


def run_worker(job_id: str, deps) -> None:
    """Entry point of the worker invocation."""
    js = JobStore(deps.backend)
    job = js.get_raw(job_id)
    if job is None or job.get("status") != "queued":
        # Async invokes can be delivered twice (or retried after a timeout): never run a job twice, it costs money.
        log.warning("worker for job %s: nothing to do (%s)", job_id, job.get("status") if job else "no such job")
        return
    job["status"] = "running"
    js.save(job)
    spec = deps.backend.read_json(f"jobs/{job_id}.spec.json") or {}
    tmp = Path(tempfile.mkdtemp(prefix="aigv2_job_"))
    cancel.set_external(lambda: js.cancel_requested(job_id))
    cancel.clear()
    try:
        names = ([spec["intake"]] if spec.get("intake") else []) + list(spec.get("inputs") or [])
        local = {}
        for n in names:
            data = deps.backend.read_bytes(f"jobs/{job_id}/inputs/{n}")
            if data is None:
                raise FileNotFoundError(f"uploaded file {n} is missing from storage")
            (tmp / n).write_bytes(data)
            local[n] = tmp / n
        execute(job, spec, deps, local.get(spec.get("intake")), [local[n] for n in spec.get("inputs") or []])
    except Exception as e:  # input staging failed
        log.exception("worker for job %s failed before running", job_id)
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
    finally:
        cancel.set_external(None)
        js.save(job)
        js.release(job_id)
        shutil.rmtree(tmp, ignore_errors=True)
