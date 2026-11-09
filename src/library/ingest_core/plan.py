"""Build and read the ingest plan: every input file, ordered, with a folder.

``build_plan`` writes ``plan.json`` and ``order_report.md`` into ``out_dir`` so
the user can review (and hand-edit folders) before the pilot and the paid run.
"""

import json
from datetime import date
from pathlib import Path

from src.library.ingest_core.ordering import order_files, scan_file, write_order_report
from src.library.ingest_core.runner import PlanEntry

PLAN_NAME = "plan.json"
REPORT_NAME = "order_report.md"


def _library_folders(library_dir: Path) -> tuple[list[str], dict[str, str]]:
    """Folder names in the library and a map of file name -> top-level folder."""
    folders = sorted(p.name for p in library_dir.iterdir() if p.is_dir()) if library_dir.is_dir() else []
    by_name: dict[str, str] = {}
    for f in sorted(library_dir.rglob("*")) if library_dir.is_dir() else []:
        if f.suffix.lower() not in (".docx", ".pdf") or not f.is_file():
            continue
        rel = f.relative_to(library_dir)
        if len(rel.parts) < 2 or "failed-processing" in rel.parts:
            continue
        by_name.setdefault(f.name, rel.parts[0])
    return folders, by_name


def build_plan(input_dir: Path, library_dir: Path, client, out_dir: Path) -> list[PlanEntry]:
    """Scan, order and assign a folder to every .docx/.pdf in ``input_dir``.

    A file with a same-named file in ``library_dir`` takes that file's folder
    for free; any other processable file is classified by ``client`` against
    the existing library folder names.
    """
    from src.library.ingester import LibraryIngester

    input_dir, library_dir, out_dir = Path(input_dir), Path(library_dir), Path(out_dir)
    files = sorted(
        f for f in input_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in (".docx", ".pdf") and not f.name.startswith("~$")
    )
    ordered = order_files([scan_file(f) for f in files])
    folders, by_name = _library_folders(library_dir)

    previous: dict[str, str] = {}
    prev_file = out_dir / PLAN_NAME
    if prev_file.exists():
        try:
            for r in json.loads(prev_file.read_text(encoding="utf-8")):
                if isinstance(r, dict) and isinstance(r.get("path"), str):
                    previous[r["path"]] = r.get("folder") if isinstance(r.get("folder"), str) else ""
        except (OSError, ValueError):
            previous = {}

    ingester = None
    classify_errors: list[tuple[str, str]] = []
    rows = []
    for o in ordered:
        folder = ""
        classify_error = None
        reason = o.skipped_reason
        if reason is None:
            key = str(o.scan.path.resolve())
            folder = by_name.get(o.scan.path.name, "")
            if not folder and previous.get(key):
                folder = previous[key]  # kept from the earlier plan.json (may be hand-edited)
            elif not folder:
                if ingester is None:
                    ingester = LibraryIngester(library_dir, api_key=getattr(client, "api_key", None) or "unused")
                    ingester.client = client
                folder, classify_error = ingester._classify_file_checked(o.scan.path, folders)
                folder = folder or ""
                if classify_error:
                    classify_errors.append((o.scan.path.name, classify_error))
                if folder and folder not in folders:
                    folders.append(folder)
                if not folder:
                    reason = "no_folder"
        rows.append({
            "path": str(o.scan.path.resolve()),
            "folder": folder,
            "order_date": o.order_date.isoformat() if o.order_date else None,
            "basis": o.basis,
            "fmt": o.scan.fmt,
            "text_hash": o.scan.text_hash,
            "skipped_reason": reason,
            **({"classify_error": classify_error} if classify_error else {}),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PLAN_NAME).write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_order_report(ordered, out_dir / REPORT_NAME)
    missing = [Path(r["path"]).name for r in rows if r["skipped_reason"] == "no_folder"]
    section = ["", "## Needs a folder (edit plan.json)", ""]
    section += [f"- {n}" for n in missing] or ["- none"]
    if classify_errors:
        section += ["", f"## Classification FAILED for {len(classify_errors)} file(s)", ""]
        section += [f"- {n}: {err}" for n, err in classify_errors]
    with open(out_dir / REPORT_NAME, "a", encoding="utf-8") as f:
        f.write("\n".join(section) + "\n")
    return _to_entries(rows)


class PlanError(ValueError):
    """plan.json has an invalid entry."""


def _to_entries(rows: list[dict]) -> list[PlanEntry]:
    out = []
    for n, r in enumerate(rows):
        where = r.get("path", "?") if isinstance(r, dict) else "?"
        try:
            if not isinstance(r, dict):
                raise TypeError("entry is not an object")
            reason = r.get("skipped_reason")
            folder = r["folder"]
            if not isinstance(folder, str):
                raise TypeError("folder is not text")
            if reason and not (reason == "no_folder" and folder.strip()):
                continue
            if not folder.strip():
                raise ValueError("folder is empty")
            od = r["order_date"]
            out.append(PlanEntry(
                path=Path(r["path"]),
                folder=folder,
                order_date=date.fromisoformat(od) if od else None,
                fmt=r["fmt"],
                text_hash=r["text_hash"],
            ))
        except (KeyError, TypeError, ValueError) as e:
            why = f"missing {e}" if isinstance(e, KeyError) else str(e)
            raise PlanError(f"plan.json entry {n} ({where}) is invalid: {why}") from e
    return out


def load_plan(out_dir: Path) -> list[PlanEntry]:
    """Read ``plan.json`` from disk (never cached) and return processable entries.

    Skipped entries are dropped, except a ``no_folder`` entry whose folder was
    filled in by hand.
    """
    rows = json.loads((Path(out_dir) / PLAN_NAME).read_text(encoding="utf-8"))
    return _to_entries(rows)
