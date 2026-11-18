"""AIG v2 test UI API: start / build / regenerate / re-QC runs as background jobs and expose run artifacts.

Local-dev oriented: jobs run in threads of this process, one at a time (CostMeter diffs shared counters, so two
concurrent builds would mix their costs). Lambda needs staged checkpoints instead (see the deployment plan).
"""

import logging
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.aigv2 import cancel, jobs, pipeline
from src.aigv2.config import load_settings
from src.aigv2.intake.template import build_template
from src.aigv2.library_sync import refresh_if_stale
from src.aigv2.preflight import PreflightStop
from src.aigv2.store import RunStore, default_backend

router = APIRouter()
log = logging.getLogger(__name__)

_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
}
_JOBS: dict[str, dict] = {}
_RUN_LOCK = threading.Lock()
_DEPS_LOCK = threading.Lock()


class BuildBody(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class UploadFileSpec(BaseModel):
    name: str
    content_type: str = "application/octet-stream"


class PresignBody(BaseModel):
    files: list[UploadFileSpec] = Field(default_factory=list)
    intake: Optional[str] = None  # the name (as in files) of the intake template, if any


class StagedStartBody(BaseModel):
    upload_id: str
    intake: Optional[str] = None
    files: list[str] = Field(default_factory=list)


class RegenBody(BaseModel):
    days: list[int] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)


def _deps(request: Request) -> pipeline.Deps:
    state = request.app.state
    with _DEPS_LOCK:
        if jobs.remote_enabled():
            # On Lambda the web side only reads and writes runs and job records in S3. The library (a 650-file sync
            # that took ~16 s on a cold instance), the Google and model clients are the worker's business.
            if getattr(state, "aigv2_deps", None) is None:
                state.aigv2_deps = SimpleNamespace(backend=default_backend(load_settings()))
            return state.aigv2_deps
        if getattr(state, "aigv2_deps", None) is not None and refresh_if_stale():
            state.aigv2_deps = None  # library edited in Library & QC: rebuild deps so Library re-reads its files
        if getattr(state, "aigv2_deps", None) is None:
            state.aigv2_deps = pipeline.default_deps()
        return state.aigv2_deps


def _store(request: Request, run_id: str) -> RunStore:
    deps = _deps(request)
    try:
        store = RunStore(deps.backend, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not store.has("trip_plan.json"):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return store


def _job(request: Request, kind: str, run_id: Optional[str], spec: Optional[dict] = None,
         intake_path: Optional[Path] = None, paths: Optional[list[Path]] = None) -> dict:
    """Start a job. Locally: a thread of this process (one at a time). On Lambda: an asynchronous invocation of this
    same function, with the job record in S3 so any instance can report on it (see src/aigv2/jobs.py)."""
    spec = spec or {}
    deps = _deps(request)
    if jobs.remote_enabled():
        job = jobs.submit(deps, kind, run_id, spec, intake_path, paths)
        if job is None:
            raise HTTPException(status_code=409, detail="Another job is still running; wait for it to finish")
        return job
    if any(j["status"] in ("queued", "running") for j in _JOBS.values()):
        raise HTTPException(status_code=409, detail="Another job is still running; wait for it to finish")
    log.info("job queued kind=%s run_id=%s", kind, run_id)
    job = jobs.new_job(kind, run_id)
    _JOBS[job["id"]] = job

    def work():
        with _RUN_LOCK:
            cancel.clear()  # a stale request from an earlier job must not stop this one
            jobs.execute(job, spec, deps, intake_path, paths)

    threading.Thread(target=work, daemon=True).start()
    return job


def _find_job(request: Request, job_id: str) -> Optional[dict]:
    if jobs.remote_enabled():
        return jobs.JobStore(_deps(request).backend).get(job_id)
    return _JOBS.get(job_id)


def _run_summary(store: RunStore) -> dict:
    trip = store.load_json("trip_plan.json") or {}
    cost = store.load_json("cost.json") or {}
    names = store.names()
    return {
        "run_id": store.run_id,
        "title": " & ".join(trip.get("client_names") or []),
        "stage": "cancelled" if "cancelled.json" in names else "built" if "guide.docx" in names else ("started" if "questions.json" in names else "new"),
        "total_usd": cost.get("total_usd"),
        "ai_usd": (cost.get("ai") or {}).get("total_usd"),
        "google_usd": (cost.get("google") or {}).get("total_usd"),
    }


@router.get("/aigv2/template")
async def intake_template():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "intake_template.docx"
        build_template(path)
        data = path.read_bytes()
    return Response(data, media_type=_MIME["docx"],
                    headers={"Content-Disposition": "attachment; filename=intake_template.docx"})


@router.get("/aigv2/runs")
async def list_runs(request: Request):
    deps = _deps(request)
    out = []
    for rid in RunStore.list_runs(deps.backend):
        try:
            store = RunStore(deps.backend, rid)
            if store.has("trip_plan.json"):
                out.append(_run_summary(store))
        except ValueError:
            continue
    return {"runs": out}


@router.get("/aigv2/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    store = _store(request, run_id)
    names = store.names()
    questions = (store.load_json("questions.json") or {}).get("questions", [])
    trip = store.load_json("trip_plan.json") or {}
    plan = store.load_json("plan.json") or {}
    return {
        **_run_summary(store),
        "questions": questions,
        "plan_items": (store.load_json("plan_review.json") or {}).get("items", []),
        "plan_failed": (store.load_json("plan_review.json") or {}).get("failed", []),
        "answers": store.load_json("answers.json"),
        "trip": trip,
        "day_count": len(plan.get("days", [])),
        "cost": store.load_json("cost.json"),
        "cost_history": (store.load_json("cost_history.json") or {}).get("runs", []),
        "qc": store.load_json("qc_report.json"),
        "files": [n for n in names if not n.startswith("inputs/") and n.rsplit(".", 1)[-1] in _MIME],
        "regen_sections": list(pipeline.REGEN_SECTIONS),
    }


def _not_cancelled(store: RunStore) -> None:
    if store.has("cancelled.json"):
        raise HTTPException(status_code=409, detail="run was cancelled; restore it first")


def _active_job(request: Request, run_id: Optional[str] = None) -> Optional[dict]:
    if jobs.remote_enabled():
        job = jobs.JobStore(_deps(request).backend).active()
        return job if job is not None and (run_id is None or job["run_id"] == run_id) else None
    return next((j for j in _JOBS.values() if j["status"] in ("queued", "running")
                 and (run_id is None or j["run_id"] == run_id)), None)


def _request_cancel(request: Request, job: dict) -> None:
    if jobs.remote_enabled():
        jobs.JobStore(_deps(request).backend).request_cancel(job["id"])  # the worker invocation polls this flag
    else:
        cancel.request()


@router.post("/aigv2/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str):
    """Stop the run's job (if any) before its next paid call and mark the run cancelled. Nothing is deleted."""
    store = _store(request, run_id)
    job = _active_job(request, run_id)
    if job is not None:
        _request_cancel(request, job)
    cost = store.load_json("cost.json") or {}
    store.save_json("cancelled.json", {"at": datetime.now(timezone.utc).isoformat(),
                                       "stage": job["kind"] if job else _run_summary(store)["stage"],
                                       "spent_usd": cost.get("total_usd")})
    return {"run_id": run_id, "cancelling": job is not None}


@router.post("/aigv2/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    """Cancel a job that has no run yet (the Start step)."""
    job = _find_job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    if job["status"] in ("queued", "running"):
        _request_cancel(request, job)
    return {"id": job_id, "cancelling": job["status"] in ("queued", "running")}


@router.post("/aigv2/runs/{run_id}/restore")
async def restore_run(request: Request, run_id: str):
    store = _store(request, run_id)
    store.delete("cancelled.json")
    return {"run_id": run_id}


@router.get("/aigv2/runs/{run_id}/files/{name:path}")
async def get_file(request: Request, run_id: str, name: str):
    store = _store(request, run_id)
    if name not in store.names():  # whitelist against the run's own listing: no traversal possible
        raise HTTPException(status_code=404, detail="No such file")
    data = store.load_bytes(name)
    if data is None:
        raise HTTPException(status_code=404, detail="No such file")
    ext = name.rsplit(".", 1)[-1]
    return Response(data, media_type=_MIME.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition": f'attachment; filename="{Path(name).name}"'})


@router.get("/aigv2/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    job = _find_job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return job


async def _save_uploads(files: list[UploadFile], tmp: Path) -> list[Path]:
    paths = []
    for f in files:
        name = Path(f.filename or "").name
        if not name:
            continue
        p = tmp / name
        n = 2
        while p.exists():  # same file name picked from two folders: keep both (a-2.pdf, a-3.pdf)
            p = tmp / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        p.write_bytes(await f.read())
        paths.append(p)
    return paths


@router.post("/aigv2/start")
async def start(request: Request, intake: Optional[UploadFile] = File(None),
                attachments: list[UploadFile] = File(default_factory=list)):
    deps = _deps(request)
    if intake is not None and not (intake.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="The intake template must be a .docx")
    tmp = Path(tempfile.mkdtemp(prefix="aigv2_in_"))
    intake_path = (await _save_uploads([intake], tmp))[0] if intake is not None and intake.filename else None
    paths = await _save_uploads(attachments, tmp)
    if intake_path is None and not paths:
        raise HTTPException(status_code=400, detail="Upload an intake template and/or at least one attachment")

    return _job(request, "start", None, {}, intake_path, paths)


def _unique_names(names: list[str]) -> list[str]:
    """Safe, distinct file names (same name picked from two folders: keep both as a-2.pdf, a-3.pdf)."""
    out: list[str] = []
    for raw in names:
        name = Path(raw or "").name
        if not name or name in (".", ".."):
            raise HTTPException(status_code=400, detail=f"Bad file name {raw!r}")
        base, n = name, 2
        while name in out:
            name = f"{Path(base).stem}-{n}{Path(base).suffix}"
            n += 1
        out.append(name)
    return out


@router.post("/aigv2/uploads/presign")
async def presign_uploads(request: Request, body: PresignBody):
    """Presigned PUT URLs so the browser uploads straight to S3 (a request through Lambda is capped at 6 MB).
    use_presigned is false on a backend that cannot presign (local disk): the page then posts the files to /start."""
    if not body.files:
        raise HTTPException(status_code=400, detail="No files to upload")
    backend = _deps(request).backend
    names = _unique_names([f.name for f in body.files])
    upload_id = secrets.token_hex(8)
    files = []
    for spec, name in zip(body.files, names):
        key = f"uploads/{upload_id}/{name}"
        files.append({"name": name, "original": spec.name, "key": key,
                      "presigned_url": backend.generate_presigned_put(key, content_type=spec.content_type)})
    return {"upload_id": upload_id, "files": files, "use_presigned": all(f["presigned_url"] for f in files)}


@router.post("/aigv2/start-staged")
async def start_staged(request: Request, body: StagedStartBody):
    """Start a run from files already uploaded with /aigv2/uploads/presign."""
    deps = _deps(request)
    if not body.upload_id.isalnum():
        raise HTTPException(status_code=400, detail="Bad upload id")
    if body.intake is not None and not body.intake.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="The intake template must be a .docx")
    if body.intake is None and not body.files:
        raise HTTPException(status_code=400, detail="Upload an intake template and/or at least one attachment")
    names = _unique_names(([body.intake] if body.intake else []) + body.files)
    if names != ([body.intake] if body.intake else []) + body.files:
        raise HTTPException(status_code=400, detail="Use the file names returned by /aigv2/uploads/presign")
    prefix = f"uploads/{body.upload_id}"
    missing = [n for n in names if not deps.backend.exists(f"{prefix}/{n}")]
    if missing:
        raise HTTPException(status_code=400, detail=f"These files did not finish uploading: {', '.join(missing)}")
    if not jobs.remote_enabled():
        raise HTTPException(status_code=400, detail="Staged uploads are for Lambda; post the files to /aigv2/start")
    job = jobs.submit(deps, "start", None, {}, staged={"prefix": prefix, "intake": body.intake, "inputs": body.files})
    if job is None:
        raise HTTPException(status_code=409, detail="Another job is still running; wait for it to finish")
    return job


@router.post("/aigv2/runs/{run_id}/plan")
async def plan(request: Request, run_id: str, body: BuildBody):
    """Optional checkpoint between Start and Build: plan the guide and return the gaps (restaurants) as job.questions."""
    store, deps = _store(request, run_id), _deps(request)
    _not_cancelled(store)

    return _job(request, "plan", run_id, {"answers": body.answers})


@router.post("/aigv2/runs/{run_id}/build")
async def build(request: Request, run_id: str, body: BuildBody):
    store, deps = _store(request, run_id), _deps(request)
    _not_cancelled(store)

    return _job(request, "build", run_id, {"answers": body.answers})


@router.post("/aigv2/runs/{run_id}/regenerate")
async def regenerate(request: Request, run_id: str, body: RegenBody):
    store, deps = _store(request, run_id), _deps(request)
    _not_cancelled(store)

    return _job(request, "regenerate", run_id, {"days": body.days, "sections": body.sections})


@router.post("/aigv2/runs/{run_id}/qc")
async def requalify(request: Request, run_id: str, file: UploadFile = File(...)):
    store, deps = _store(request, run_id), _deps(request)
    _not_cancelled(store)
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Upload the edited guide as a .docx")
    tmp = Path(tempfile.mkdtemp(prefix="aigv2_qc_"))
    path = (await _save_uploads([file], tmp))[0]

    return _job(request, "qc", run_id, {}, None, [path])
