"""Drive a paid ingest run: extract in threads, clean and merge in plan order.

Designed for a long paid run over hundreds of files:

- Extraction runs on up to ``workers`` threads, at most ``workers`` files ahead
  of the merge cursor, so a cost-ceiling overshoot is bounded by ``workers``.
- Cleaning, merging and index updates happen in the main thread strictly in
  plan order (the DB service and merge are not thread-safe).
- Any ``Exception`` while extracting, cleaning or merging one file is logged
  and the file recorded under ``failed``; the run continues. ``KeyboardInterrupt``
  and ``SystemExit`` propagate, but the ``finally`` block still saves the index.
- Resume: a file whose ``_processed_files[rel_key].text_hash`` matches is skipped.
- One JSON line per file is appended (and flushed) to ``log_dir/ingest_log.jsonl``.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from src.library.ingest_core.clean import clean_extraction, is_v2_generated
from src.library.ingest_core.extract import extract_file
from src.library.ingest_core.merge import FileMeta, MergeStats, merge_extraction
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS
from src.library.ui.services.db_service import LibraryDBService

LOG_NAME = "ingest_log.jsonl"


@dataclass
class PlanEntry:
    path: Path
    folder: str
    order_date: date | None
    fmt: str
    text_hash: str


@dataclass
class IngestReport:
    processed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    stats: MergeStats = field(default_factory=MergeStats)
    dropped: list[dict] = field(default_factory=list)
    cost_usd: float | None = None
    stopped_on_ceiling: bool = False


def _rel_key(entry: PlanEntry) -> str:
    return f"{entry.folder}/{Path(entry.path).name}"


def _covered(data: dict) -> list[str]:
    cov = data.get("covered_cities")
    if not isinstance(cov, list):
        return []
    return [c for c in cov if isinstance(c, str) and c.strip()]


def _has_items(container: dict, lists: tuple[str, ...]) -> bool:
    return any(isinstance(container.get(n), list) and container[n] for n in lists)


def _has_content(data: dict) -> bool:
    if _covered(data) or _has_items(data, CITY_LISTS):
        return True
    cc = data.get("country_content")
    entries = cc.values() if isinstance(cc, dict) else cc if isinstance(cc, list) else []
    return any(isinstance(e, dict) and _has_items(e, COUNTRY_LISTS) for e in entries)


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


def run_ingest(
    plan: list[PlanEntry],
    db: LibraryDBService,
    client,
    *,
    log_dir: Path,
    workers: int = 5,
    max_usd: float | None = None,
    checkpoint_every: int = 10,
) -> IngestReport:
    """Ingest ``plan`` in order into ``db``. See the module docstring."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if checkpoint_every < 1:
        raise ValueError("checkpoint_every must be >= 1")
    if max_usd is not None and client.cost_usd is None:
        raise ValueError("model has no known price; cannot enforce --max-usd")

    report = IngestReport()
    per_file_figures = workers == 1

    processed_index = db._index.get("_processed_files", {})
    skip: list[str | None] = []
    for entry in plan:
        prev = processed_index.get(_rel_key(entry))
        if isinstance(prev, dict) and prev.get("text_hash") == entry.text_hash:
            skip.append("already_processed")
        elif is_v2_generated(Path(entry.path)):
            skip.append("v2_generated")
        else:
            skip.append(None)
    todo = [i for i, reason in enumerate(skip) if reason is None]

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / LOG_NAME, "a", encoding="utf-8")

    def write_log(entry: PlanEntry, status: str, reason: str | None = None, *,
                  stats: MergeStats | None = None, dropped: list | None = None,
                  extraction=None, error: str | None = None) -> None:
        figures = extraction is not None and per_file_figures
        line = {
            "file": _rel_key(entry),
            "status": status,
            "reason": reason,
            "order_date": entry.order_date.isoformat() if entry.order_date else None,
            "fmt": entry.fmt,
            "stats": asdict(stats) if stats is not None else None,
            "dropped": dropped or [],
            "prompt_tokens": extraction.prompt_tokens if figures else None,
            "completion_tokens": extraction.completion_tokens if figures else None,
            "usd": extraction.usd if figures else None,
            "error": error,
        }
        log.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        log.flush()

    def fail(entry: PlanEntry, reason: str, message: str, extraction=None,
             error: str | None = None) -> None:
        rel = _rel_key(entry)
        report.failed.append((rel, message))
        write_log(entry, "failed", reason, extraction=extraction, error=error or message)
        print(f"[ingest] FAILED {rel}: {message}")

    executor = ThreadPoolExecutor(max_workers=workers)
    futures: dict[int, object] = {}
    next_submit = 0
    merged_since_checkpoint = 0

    def top_up() -> None:
        nonlocal next_submit
        while (not report.stopped_on_ceiling and next_submit < len(todo)
               and len(futures) < workers):
            if max_usd is not None:
                spent = client.cost_usd
                if spent is not None and spent >= max_usd:
                    report.stopped_on_ceiling = True
                    print(f"[ingest] cost ceiling reached (${spent:.2f} >= ${max_usd:.2f}); "
                          "no new extractions")
                    return
            i = todo[next_submit]
            futures[i] = executor.submit(extract_file, client, Path(plan[i].path))
            next_submit += 1

    try:
        for i, entry in enumerate(plan):
            rel = _rel_key(entry)
            if skip[i] is not None:
                report.skipped.append((rel, skip[i]))
                write_log(entry, "skipped", skip[i])
                continue
            top_up()
            fut = futures.pop(i, None)
            if fut is None:  # not submitted: ceiling reached
                report.skipped.append((rel, "cost_ceiling"))
                write_log(entry, "skipped", "cost_ceiling")
                continue

            extraction = None
            try:
                extraction = fut.result()
                if extraction is None:
                    fail(entry, "extraction_failed", "extraction returned nothing")
                    continue
                if not isinstance(extraction.data, dict):
                    raise TypeError(
                        f"extraction data is {type(extraction.data).__name__}, not an object")
                cleaned, dropped = clean_extraction(extraction.data)
                if not _has_content(cleaned):
                    fail(entry, "empty", "no cities or items after cleaning", extraction)
                    continue
                meta = FileMeta(source_file=rel, order_date=entry.order_date,
                                fmt=entry.fmt, folder=entry.folder)
                stats = merge_extraction(db, cleaned, meta)
                covered = _covered(cleaned)
                db.record_processed_file(rel, {
                    "text_hash": entry.text_hash,
                    "order_date": entry.order_date.isoformat() if entry.order_date else None,
                    "fmt": entry.fmt,
                    "folder": entry.folder,
                    "covered_cities": covered,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
                db.add_folder_coverage(entry.folder, covered)
            except Exception as e:  # one bad file must never abort the run
                fail(entry, "exception", _err(e), extraction, error=_err(e))
                continue

            report.processed.append(rel)
            report.stats += stats
            report.dropped.extend({**d, "file": rel} for d in dropped)
            write_log(entry, "processed", stats=stats, dropped=dropped, extraction=extraction)
            print(f"[ingest] {rel}: +{stats.added} ~{stats.replaced} ={stats.unchanged} "
                  f"older:{stats.skipped_older} dropped:{len(dropped)}")
            merged_since_checkpoint += 1
            if merged_since_checkpoint >= checkpoint_every:
                db.save_index()
                merged_since_checkpoint = 0
    finally:
        try:
            db.save_index()
        finally:
            # do not wait for in-flight calls on an interrupt; drop queued ones
            executor.shutdown(wait=False, cancel_futures=True)
            log.close()

    report.cost_usd = client.cost_usd
    return report
