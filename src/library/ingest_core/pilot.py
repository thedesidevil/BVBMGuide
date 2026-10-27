"""Pilot: run a handful of files through each candidate model, write nothing to any library."""

import json
from pathlib import Path

from src.library.ingest_core.extract import extract_file
from src.library.ingest_core.runner import PlanEntry

HIGH_PROMPT_TOKENS = 100_000
_MULTI_MARKERS = (" and ", "&", "+")


class PilotError(Exception):
    """A model did not answer the connectivity probe."""


def _is_multi(folder: str) -> bool:
    return any(m in folder for m in _MULTI_MARKERS)


def _size(e: PlanEntry) -> int:
    try:
        return Path(e.path).stat().st_size
    except OSError:
        return 0


def select_pilot_files(plan: list[PlanEntry], count: int = 10) -> list[PlanEntry]:
    """Pick up to ``count`` entries covering formats, size, multi-country and folders."""
    ordered = sorted(plan, key=lambda e: (e.folder, Path(e.path).name))
    picked: list[PlanEntry] = []

    def add(e: PlanEntry | None) -> None:
        if e is not None and all(e is not p for p in picked):
            picked.append(e)

    add(next((e for e in ordered if e.fmt == "old"), None))
    add(next((e for e in ordered if e.fmt != "old"), None))
    add(max(ordered, key=lambda e: (_size(e), e.folder, Path(e.path).name), default=None))
    add(next((e for e in ordered if _is_multi(e.folder)), None))
    if len({p.folder for p in picked}) < 2:
        first = picked[0].folder if picked else None
        add(next((e for e in ordered if e.folder != first), None))

    by_folder: dict[str, list[PlanEntry]] = {}
    for e in ordered:
        by_folder.setdefault(e.folder, []).append(e)
    queues = [list(v) for _, v in sorted(by_folder.items())]
    while len(picked) < count and any(queues):
        for q in queues:
            while q and any(q[0] is p for p in picked):
                q.pop(0)
            if q and len(picked) < count:
                add(q.pop(0))
    return picked[:count]


def _counts(data: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[k] = len(v)
    cc = data.get("country_content")
    for entry in cc if isinstance(cc, list) else []:
        if isinstance(entry, dict):
            for k, v in entry.items():
                if isinstance(v, list):
                    out[f"country:{k}"] = out.get(f"country:{k}", 0) + len(v)
    return out


def _names(data: dict, key: str) -> list[str]:
    items = data.get(key)
    return [i["name"] for i in items if isinstance(i, dict) and isinstance(i.get("name"), str)] if isinstance(items, list) else []


def run_pilot(entries: list[PlanEntry], models: list[str], out_dir: Path, clients: dict | None = None) -> None:
    """Probe each model, extract every entry with each model, write the reports.

    ``clients`` maps model name -> client; by default each model gets
    ``get_ai_client(model=name)``. Raises ``PilotError`` if a probe fails; no
    other model is substituted. Nothing is written to any library database.
    """
    if clients is None:
        from src.common.ai_provider import get_ai_client

        clients = {m: get_ai_client(model=m) for m in models}
    for m in models:
        try:
            clients[m].complete("Reply with the single word OK.", max_tokens=8, temperature=0)
        except Exception as e:
            raise PilotError(f"model {m} did not answer the connectivity probe: {type(e).__name__}: {e}") from e

    files = []
    for e in entries:
        row = {"file": f"{e.folder}/{Path(e.path).name}", "folder": e.folder, "fmt": e.fmt, "models": {}}
        for m in models:
            ex = extract_file(clients[m], Path(e.path))
            if ex is None:
                row["models"][m] = {"failed": True}
                continue
            row["models"][m] = {
                "failed": False,
                "chunks": ex.chunks,
                "prompt_tokens": ex.prompt_tokens,
                "completion_tokens": ex.completion_tokens,
                "usd": ex.usd,
                "over_100k_prompt": ex.prompt_tokens > HIGH_PROMPT_TOKENS,
                "counts": _counts(ex.data),
                "restaurants": _names(ex.data, "restaurants"),
                "attractions": _names(ex.data, "attractions"),
            }
        files.append(row)

    summary = {}
    for m in models:
        usds = [r["models"][m]["usd"] for r in files
                if not r["models"][m]["failed"] and r["models"][m]["usd"] is not None]
        summary[m] = {"avg_usd_per_file": sum(usds) / len(usds) if usds else None, "files_measured": len(usds)}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pilot_report.json").write_text(
        json.dumps({"models": summary, "files": files}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "pilot_report.md").write_text(_markdown(models, summary, files), encoding="utf-8")


def _markdown(models, summary, files) -> str:
    L = ["# Pilot report", "", "## Average cost per file", ""]
    for m in models:
        avg = summary[m]["avg_usd_per_file"]
        L.append(f"- {m}: {'unknown' if avg is None else f'${avg:.4f}'} per file ({summary[m]['files_measured']} measured)")
    L += ["", "## Per file and model", "",
          "| file | fmt | model | chunks | prompt tok | completion tok | usd | item counts | flag |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in files:
        for m in models:
            x = r["models"][m]
            if x["failed"]:
                L.append(f"| {r['file']} | {r['fmt']} | {m} | | | | | FAILED | |")
                continue
            counts = ", ".join(f"{k}={v}" for k, v in sorted(x["counts"].items()))
            usd = "n/a" if x["usd"] is None else f"{x['usd']:.4f}"
            flag = "prompt over 100K tokens (higher Haiku tier)" if x["over_100k_prompt"] else ""
            L.append(f"| {r['file']} | {r['fmt']} | {m} | {x['chunks']} | {x['prompt_tokens']} | "
                     f"{x['completion_tokens']} | {usd} | {counts} | {flag} |")
    L += ["", "## Side by side: restaurant and attraction names", ""]
    for r in files:
        L += [f"### {r['file']}", ""]
        for kind in ("restaurants", "attractions"):
            L.append(f"**{kind}**")
            for m in models:
                x = r["models"][m]
                names = "FAILED" if x["failed"] else "; ".join(x[kind]) or "(none)"
                L.append(f"- {m}: {names}")
            L.append("")
    return "\n".join(L) + "\n"
