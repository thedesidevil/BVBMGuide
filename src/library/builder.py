"""Build the library database from the AIG library through the shared ingest core.

``LibraryBuilder`` is a thin CLI caller of ``src.library.ingest_core``: it scans
and orders the library files, then runs ``run_ingest`` (extract, clean, ordered
newer-wins merge, provenance, index/coverage, country shards).
``LibraryDatabase`` is the read-only sharded DB reader.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

from src.common.ai_provider import get_ai_client


console = Console()

DB_VERSION = "1.2"
CHECKPOINT_EVERY = 10
LOG_DIR_NAME = "_logs"
MAX_UNCAPPED_FILES = 5
LEGACY_INDEX_MESSAGE = (
    "This library was built by the old ingester: its processed-file records have no "
    "content hash, so a rebuild would re-extract and re-pay for every file. Use the "
    "plan/rebuild workflow into a new folder instead."
)


class LibraryBuilder:
    """Builds the library database from the AIG library using the ingest core."""

    def __init__(
        self,
        library_path: str | Path,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        workers: int = 5,
    ):
        self.library_path = Path(library_path)
        self.workers = workers
        self.client = get_ai_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=600.0,
            max_retries=1,
        )

    def _discover(self) -> list[tuple[Path, str]]:
        """``(path, folder)`` for every DOCX/PDF under a top-level subfolder.

        ``folder`` is the top-level subfolder name. Files directly in
        ``library_path`` and anything under ``failed-processing/`` are ignored.
        """
        found = []
        for f in sorted(self.library_path.rglob("*")):
            if f.suffix.lower() not in (".docx", ".pdf") or not f.is_file():
                continue
            if f.name.startswith("~$"):
                continue
            rel = f.relative_to(self.library_path)
            if len(rel.parts) < 2 or "failed-processing" in rel.parts:
                continue
            found.append((f, rel.parts[0]))
        return found

    def build_database(
        self,
        output_path: Optional[Path] = None,
        force: bool = False,
        workers: Optional[int] = None,
        max_usd: Optional[float] = None,
    ) -> dict:
        """Build or incrementally update the sharded library database.

        Scans every DOCX/PDF in the subfolders of ``library_path`` (folder =
        top-level subfolder name), orders them with ``scan_file``/``order_files``
        (duplicates, non-AIGs and unreadable files are skipped) and runs
        ``run_ingest`` against a ``LibraryDBService`` on ``output_path``. Files
        whose text hash is already recorded in ``_processed_files`` are skipped.

        ``force=True`` clears the processed-files index (and only that) so every
        file is re-extracted and re-merged. It never deletes shards: the merge is
        idempotent and newer-wins, so re-merging the same files leaves them as
        they were apart from refreshed content.

        Only directory outputs are supported; a ``.json`` path raises
        ``ValueError``. The run log goes to ``<output_path>/_logs/``.

        Cost guards (each raises ``ValueError`` before any extraction):

        - an existing index whose ``_processed_files`` holds a record without
          ``text_hash`` was built by the old ingester; every file would be
          re-extracted, so the build refuses (with or without ``force``);
        - more than ``MAX_UNCAPPED_FILES`` files to extract requires
          ``max_usd``, which is passed to ``run_ingest`` as the cost ceiling.

        Returns ``{"version", "built_at", "destinations": {city: shard},
        "_processed_files", "_folder_coverage"[, "_review_status"]}``.
        """
        from src.library.ingest_core import run_ingest
        from src.library.ingest_core.clean import is_v2_generated
        from src.library.ingest_core.ordering import order_files, scan_file
        from src.library.ingest_core.runner import PlanEntry
        from src.library.ui.services.db_service import LibraryDBService
        from src.library.ui.storage import LocalStorageBackend

        output_path = Path(output_path) if output_path is not None else Path("library_db")
        if output_path.suffix.lower() == ".json":
            raise ValueError("single-file library output is no longer supported; use a directory")
        output_path.mkdir(parents=True, exist_ok=True)

        db = LibraryDBService(LocalStorageBackend(output_path))
        existing = db._index.get("_processed_files") or {}
        if any(not (isinstance(r, dict) and r.get("text_hash")) for r in existing.values()):
            raise ValueError(LEGACY_INDEX_MESSAGE)
        if force:
            db.clear_processed_files()

        discovered = self._discover()
        folder_of = {path: folder for path, folder in discovered}
        ordered = order_files([scan_file(path) for path, _ in discovered])
        plan = [
            PlanEntry(path=o.scan.path, folder=folder_of[o.scan.path], order_date=o.order_date,
                      fmt=o.scan.fmt, text_hash=o.scan.text_hash)
            for o in ordered if o.skipped_reason is None
        ]
        skipped = [o for o in ordered if o.skipped_reason is not None]

        processed = db._index.get("_processed_files") or {}
        to_extract = [
            e for e in plan
            if (processed.get(f"{e.folder}/{e.path.name}") or {}).get("text_hash") != e.text_hash
            and not is_v2_generated(e.path)
        ]
        console.print(f"\n  Files to extract (paid AI calls): {len(to_extract)}")
        if len(to_extract) > MAX_UNCAPPED_FILES and max_usd is None:
            raise ValueError(
                f"{len(to_extract)} files would be extracted; --max-usd is required "
                f"for more than {MAX_UNCAPPED_FILES} files"
            )
        db._index["version"] = DB_VERSION
        db._index["built_at"] = datetime.now().isoformat()

        num_workers = workers if workers is not None else self.workers
        console.print("\n[bold]Building library database...[/bold]")
        console.print(f"  Files in library:  {len(discovered)}")
        console.print(f"  Skipped by scan:   {len(skipped)}")
        console.print(f"  In plan:           {len(plan)}")
        console.print(f"  Workers:           {num_workers}\n")
        for o in skipped:
            console.print(f"  [dim]skip {o.scan.path.relative_to(self.library_path)}: {o.skipped_reason}[/dim]")

        report = run_ingest(plan, db, self.client, log_dir=output_path / LOG_DIR_NAME,
                            workers=num_workers, max_usd=max_usd,
                            checkpoint_every=CHECKPOINT_EVERY)

        database: dict = {
            "version": db._index.get("version", DB_VERSION),
            "built_at": db._index.get("built_at"),
            "destinations": {name: db.get_city_data(name) or {} for name in db.list_city_shards()},
            "_processed_files": dict(db._index.get("_processed_files", {})),
            "_folder_coverage": dict(db.get_folder_coverage()),
        }
        if "_review_status" in db._index:
            database["_review_status"] = db._index["_review_status"]

        console.print(f"\n[bold green]✓ Database saved to {output_path}[/bold green]")
        self._print_summary(report)
        return database

    def _print_summary(self, report) -> None:
        s = report.stats
        console.print("\n[bold]Ingest Summary[/bold]\n")
        console.print(f"  Processed: {len(report.processed)}")
        console.print(f"  Skipped:   {len(report.skipped)}")
        console.print(f"  Failed:    {len(report.failed)}")
        console.print(f"  Items:     +{s.added} added, ~{s.replaced} replaced, "
                      f"={s.unchanged} unchanged, {s.skipped_older} older skipped, "
                      f"{s.protected} protected, {s.blocked} blocked")
        console.print(f"  Dropped:   {len(report.dropped)}")
        for rel, message in report.failed:
            console.print(f"  [yellow]failed[/yellow] {rel}: {message}")
        console.print()


class LibraryDatabase:
    """Query interface for the pre-built library database.

    Auto-detects format: if db_path ends in '.json' → flat legacy file;
    otherwise → sharded directory with _index.json + per-destination files.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._sharded = self.db_path.suffix != '.json'
        self._data: Optional[dict] = None       # flat mode full dict, or sharded full reconstruction
        self._index: Optional[dict] = None      # sharded mode: index only
        self._dest_cache: dict[str, dict] = {}  # sharded mode: lazily loaded destination files

    def load(self) -> None:
        if not self._sharded:
            if not self.db_path.exists():
                raise FileNotFoundError(f"Library database not found: {self.db_path}")
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
        else:
            index_path = self.db_path / '_index.json'
            if not index_path.exists():
                raise FileNotFoundError(f"Library database not found: {self.db_path}")
            with open(index_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)

    def _load_dest(self, dest: str) -> dict:
        """Load and cache one destination shard."""
        if dest not in self._dest_cache:
            dest_path = self.db_path / f'{dest}.json'
            if dest_path.exists():
                with open(dest_path, 'r', encoding='utf-8') as f:
                    self._dest_cache[dest] = json.load(f)
            else:
                self._dest_cache[dest] = {}
        return self._dest_cache[dest]

    @property
    def data(self) -> dict:
        """Return full database dict — loads all shards if needed (used by stats/verify)."""
        if self._data is None:
            if self._index is None:
                self.load()
            if self._sharded:
                self._data = dict(self._index)
                self._data['destinations'] = {}
                for dest_file in sorted(self.db_path.glob('*.json')):
                    if dest_file.name.startswith('_'):
                        continue
                    with open(dest_file, 'r', encoding='utf-8') as f:
                        self._data['destinations'][dest_file.stem] = json.load(f)
        return self._data

    def get_destinations(self) -> list[str]:
        if self._sharded:
            if self._index is None:
                self.load()
            return list(self._index.get('_folder_coverage', {}).keys())
        return list(self.data['destinations'].keys())

    def find_relevant_folders(self, cities: list[str]) -> dict[str, list[str]]:
        """Return {destination: [source_files]} for destinations matching any of the given cities.

        Checks city-named destination shards directly first (primary path after city routing),
        then falls back to _folder_coverage for any cities not directly matched.
        """
        if self._sharded and self._index is None:
            self.load()
        cities_lower = {c.lower().strip() for c in cities}
        result = {}

        # Primary: direct city-shard match (destinations are now city names)
        for dest in self.get_destinations():
            if dest.lower() in cities_lower:
                dest_data = self._load_dest(dest) if self._sharded else self.data['destinations'].get(dest, {})
                result[dest] = dest_data.get('source_files', [])

        # Fallback: folder coverage index (catches cities stored under a country shard)
        unmatched = cities_lower - {d.lower() for d in result}
        if unmatched:
            coverage = (self._index if self._sharded else self.data).get('_folder_coverage', {})
            for folder, covered in coverage.items():
                if unmatched & {c.lower() for c in covered}:
                    if folder not in result:
                        dest_data = self._load_dest(folder) if self._sharded else self.data['destinations'].get(folder, {})
                        result[folder] = dest_data.get('source_files', [])

        return result

    def get_restaurants(self, destination: str) -> list[dict]:
        dest_lower = destination.lower()
        if self._sharded:
            if self._index is None:
                self.load()
            for dest in self._index.get('_folder_coverage', {}):
                if dest.lower() == dest_lower:
                    return self._load_dest(dest).get('restaurants', [])
            return []
        for dest, data in self.data['destinations'].items():
            if dest.lower() == dest_lower:
                return data.get('restaurants', [])
        return []

    def get_city_data(self, city: str) -> dict:
        """Return all library data for a city, or {} if not found."""
        if self._sharded:
            if self._index is None:
                self.load()
            # Direct city-named shard (primary path)
            city_file = self.db_path / f'{city}.json'
            if city_file.exists():
                return self._load_dest(city)
            # Fallback: folder coverage (city stored under a country shard)
            city_lower = city.lower()
            coverage = self._index.get('_folder_coverage', {})
            for folder, covered_cities in coverage.items():
                if any(c.lower() == city_lower for c in covered_cities):
                    return self._load_dest(folder)
            return {}
        for dest, data in self.data.get('destinations', {}).items():
            if dest.lower() == city.lower():
                return data
        return {}
