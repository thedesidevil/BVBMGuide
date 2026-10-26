"""AIG v2 test UI API: start / build / regenerate / re-QC runs as background jobs and expose run artifacts.

Local-dev oriented: jobs run in threads of this process, one at a time (CostMeter diffs shared counters, so two
concurrent builds would mix their costs). Lambda needs staged checkpoints instead (see the deployment plan).
"""

import secrets
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.aigv2 import pipeline
from src.aigv2.intake.template import build_template
from src.aigv2.preflight import PreflightStop
from src.aigv2.store import RunStore

router = APIRouter()

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


class RegenBody(BaseModel):
    days: list[int] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)


def _deps(request: Request) -> pipeline.Deps:
    state = request.app.state
    with _DEPS_LOCK:
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


def _job(kind: str, run_id: Optional[str], fn) -> dict:
    """Run fn() in a thread under the single-job lock; fn returns a dict merged into the job's `result`."""
    if any(j["status"] in ("queued", "running") for j in _JOBS.values()):
        raise HTTPException(status_code=409, detail="Another job is still running; wait for it to finish")
    job = {"id": secrets.token_hex(4), "kind": kind, "run_id": run_id, "status": "queued", "result": None,
           "error": None, "questions": [], "cost": None, "started_at": datetime.now(timezone.utc).isoformat()}
    _JOBS[job["id"]] = job

    def work():
        with _RUN_LOCK:
            job["status"] = "running"
            try:
                job["result"] = fn(job)
                job["status"] = "done"
            except pipeline.UnansweredQuestions as e:
                job["status"], job["error"] = "error", "Some pre-flight questions still need an answer"
                job["questions"] = [q.model_dump(mode="json") for q in e.questions]
            except Exception as e:  # surface every failure to the page, with the partial cost
                job["status"] = "error"
                job["error"] = str(e) if isinstance(e, (PreflightStop, ValueError)) else f"{type(e).__name__}: {e}"
                job["run_id"] = getattr(e, "run_id", job["run_id"])
                job["cost"] = getattr(e, "run_cost", None)
                if not isinstance(e, (PreflightStop, ValueError)):
                    traceback.print_exc()

    threading.Thread(target=work, daemon=True).start()
    return job


def _run_summary(store: RunStore) -> dict:
    trip = store.load_json("trip_plan.json") or {}
    cost = store.load_json("cost.json") or {}
    names = store.names()
    return {
        "run_id": store.run_id,
        "title": " & ".join(trip.get("client_names") or []),
        "stage": "built" if "guide.docx" in names else ("started" if "questions.json" in names else "new"),
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
        "answers": store.load_json("answers.json"),
        "trip": trip,
        "day_count": len(plan.get("days", [])),
        "cost": store.load_json("cost.json"),
        "cost_history": (store.load_json("cost_history.json") or {}).get("runs", []),
        "qc": store.load_json("qc_report.json"),
        "files": [n for n in names if not n.startswith("inputs/") and n.rsplit(".", 1)[-1] in _MIME],
        "regen_sections": list(pipeline.REGEN_SECTIONS),
    }


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
async def get_job(job_id: str):
    job = _JOBS.get(job_id)
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

    def run(job):
        store, questions = pipeline.start_run(intake_path, paths, deps)
        job["run_id"] = store.run_id
        return {"run_id": store.run_id, "questions": len(questions)}

    return _job("start", None, run)


@router.post("/aigv2/runs/{run_id}/build")
async def build(request: Request, run_id: str, body: BuildBody):
    store, deps = _store(request, run_id), _deps(request)

    def run(job):
        r = pipeline.build_run(store, body.answers, deps)
        return {"docx_name": r.docx_name, "passed": r.qc.passed}

    return _job("build", run_id, run)


@router.post("/aigv2/runs/{run_id}/regenerate")
async def regenerate(request: Request, run_id: str, body: RegenBody):
    store, deps = _store(request, run_id), _deps(request)

    def run(job):
        r = pipeline.regenerate(store, body.days, body.sections, deps)
        return {"docx_name": r.docx_name, "passed": r.qc.passed}

    return _job("regenerate", run_id, run)


@router.post("/aigv2/runs/{run_id}/qc")
async def requalify(request: Request, run_id: str, file: UploadFile = File(...)):
    store, deps = _store(request, run_id), _deps(request)
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Upload the edited guide as a .docx")
    tmp = Path(tempfile.mkdtemp(prefix="aigv2_qc_"))
    path = (await _save_uploads([file], tmp))[0]

    def run(job):
        _, result, _ = pipeline.requalify(store, path, deps)
        names = [n for n in store.names() if n.startswith("requalify/")]
        return {"passed": result.passed, "findings": len(result.findings), "files": names}

    return _job("qc", run_id, run)
