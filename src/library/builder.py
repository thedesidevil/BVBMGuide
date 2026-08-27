"""Build a structured database from the AIG library using AI extraction."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF for PDF extraction
from docx import Document
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.common.ai_provider import get_ai_client
from src.common.doc_extractor import (
    repair_truncated_json as _repair_truncated_json,
    sanitize_text as _sanitize_text,
    call_and_parse as _shared_call_and_parse,
    split_into_chunks as _split_into_chunks_shared,
    merge_extraction_results as _merge_extraction_results_shared,
    LIBRARY_EXTRACTION_PROMPT,
    SINGLE_PASS_LIMIT,
    CHUNK_OVERLAP,
)


console = Console()

DB_VERSION = "1.2"
CHECKPOINT_EVERY = 10


def _checkpoint_save(database: dict, output_path: Path) -> None:
    """Write database to disk as an incremental checkpoint (flat or sharded)."""
    try:
        if output_path.suffix == '.json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(database, f, indent=2, ensure_ascii=False)
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            index = {k: v for k, v in database.items() if k != 'destinations'}
            with open(output_path / '_index.json', 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
            for dest, data in database['destinations'].items():
                safe_dest = dest.replace('/', '-').replace('\\', '-')
                with open(output_path / f'{safe_dest}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        console.print(
            f"[dim]  checkpoint saved "
            f"({len(database['_processed_files'])} files)[/dim]"
        )
    except Exception as e:
        console.print(f"[yellow]Checkpoint save failed:[/yellow] {e}")


_INCLUDED_PATTERN = re.compile(r'\bincluded\b|\bcovered\b|\bcomplementary\b|\bfree of charge\b|\bbooked\b|\bpre-booked\b', re.IGNORECASE)
_HAS_PRICE = re.compile(r'[$€£¥₹₩฿]|\b\d+\s*(USD|EUR|GBP|JPY|KZT|TRY|CHF|INR|AED|SGD|THB|MYR|IDR)\b', re.IGNORECASE)


def _clean_entry_fees(data: dict) -> None:
    """Remove entry_fee values that describe tour inclusions rather than real venue costs."""
    for attraction in data.get("attractions", []):
        fee = attraction.get("entry_fee")
        if fee and _INCLUDED_PATTERN.search(fee) and not _HAS_PRICE.search(fee):
            attraction.pop("entry_fee", None)


class LibraryBuilder:
    """Builds a structured database from the AIG library using AI."""

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
        )

    def build_database(self, output_path: Optional[Path] = None, force: bool = False, workers: Optional[int] = None) -> dict:
        """Build or incrementally update the library database.

        Scans all DOCX/PDF files in subfolders of library_path.
        Skips files whose relative-path key is already in _processed_files
        with an unchanged mtime (unless force=True).
        """
        if output_path is None:
            output_path = Path("library_db")

        existing_db = None
        processed_files: dict = {}

        if output_path.exists() and not force:
            try:
                if output_path.suffix == '.json':
                    with open(output_path, 'r', encoding='utf-8') as f:
                        existing_db = json.load(f)
                else:
                    index_path = output_path / '_index.json'
                    if index_path.exists():
                        with open(index_path, 'r', encoding='utf-8') as f:
                            existing_db = json.load(f)
                        # Load destination data from individual shard files — _index.json
                        # only holds metadata, not destinations.
                        existing_db["destinations"] = {}
                        for shard in output_path.glob("*.json"):
                            if shard.name.startswith("_"):
                                continue
                            dest_name = shard.stem
                            with open(shard, 'r', encoding='utf-8') as f:
                                existing_db["destinations"][dest_name] = json.load(f)
                processed_files = existing_db.get("_processed_files", {})
                console.print(f"[dim]Found existing database with {len(processed_files)} processed files[/dim]")
            except Exception:
                existing_db = None

        database: dict = {
            "version": DB_VERSION,
            "built_at": datetime.now().isoformat(),
            "destinations": existing_db.get("destinations", {}) if existing_db else {},
            "_processed_files": processed_files,
            "_folder_coverage": existing_db.get("_folder_coverage", {}) if existing_db else {},
        }
        if existing_db and "_review_status" in existing_db:
            database["_review_status"] = existing_db["_review_status"]

        # Discover all DOCX/PDF files (skip failed-processing/)
        all_files = [
            f for f in self.library_path.rglob("*")
            if f.suffix.lower() in (".docx", ".pdf")
            and "failed-processing" not in f.parts
        ]

        # Determine which files need processing
        files_to_process = []
        for file_path in all_files:
            rel_key = str(file_path.relative_to(self.library_path))
            file_mtime = os.path.getmtime(file_path)
            if rel_key in processed_files and processed_files[rel_key].get("mtime") == file_mtime:
                continue
            files_to_process.append(file_path)

        if not files_to_process:
            console.print("\n[green]✓ All files already processed. Database is up to date.[/green]")
            self._build_folder_coverage(database)
            return database

        num_workers = workers if workers is not None else self.workers

        console.print(f"\n[bold]Building library database...[/bold]")
        console.print(f"  Total files in library: {len(all_files)}")
        console.print(f"  Already processed:      {len(all_files) - len(files_to_process)}")
        console.print(f"  To process:             {len(files_to_process)}")
        console.print(f"  Workers:                {num_workers}\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing files...", total=len(files_to_process))

            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_to_file = {
                    executor.submit(self._process_file, fp): fp
                    for fp in files_to_process
                }

                completed_since_checkpoint = 0
                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    rel_key = str(file_path.relative_to(self.library_path))
                    destination = file_path.parent.name

                    progress.update(task, description=f"[{destination}] {file_path.name[:35]}...")

                    try:
                        file_data = future.result()
                        if file_data:
                            file_mtime = os.path.getmtime(file_path)
                            tracked_dests: set[str] = set()

                            _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips"}

                            for field in ("restaurants", "attractions", "hotels",
                                          "local_dishes", "phrases", "safety_tips", "souvenirs",
                                          "emergency_contacts", "connectivity_tips",
                                          "transport_options", "health_tips"):
                                for item in file_data.get(field) or []:
                                    if isinstance(item, dict):
                                        item["_source_file"] = rel_key
                                        item["_source_mtime"] = file_mtime
                                        if field in _MULTI_CITY_FIELDS:
                                            raw = item.get("cities") or [item.get("city", "")]
                                            dests = [c.strip().title() for c in raw if c and c.strip()] or [destination]
                                        else:
                                            raw_city = item.get("city", "").strip()
                                            dests = [raw_city.title() if raw_city else destination]
                                    else:
                                        dests = [destination]

                                    for dest in dests:
                                        if dest not in database["destinations"]:
                                            database["destinations"][dest] = {
                                                "restaurants": [], "attractions": [], "hotels": [],
                                                "local_dishes": [], "phrases": [], "safety_tips": [],
                                                "souvenirs": [], "emergency_contacts": [],
                                                "connectivity_tips": [], "transport_options": [],
                                                "health_tips": [], "source_files": [],
                                            }

                                        dest_data = database["destinations"][dest]
                                        if dest not in tracked_dests:
                                            if rel_key not in dest_data["source_files"]:
                                                dest_data["source_files"].append(rel_key)
                                            tracked_dests.add(dest)

                                        dest_data[field].append(item)

                            database["_processed_files"][rel_key] = {
                                "mtime": file_mtime,
                                "destination": destination,
                                "covered_cities": file_data.get("covered_cities", []),
                                "processed_at": datetime.now().isoformat(),
                            }

                    except Exception as e:
                        console.print(f"[yellow]Warning:[/yellow] Failed to process {rel_key}: {e}")

                    progress.advance(task)
                    completed_since_checkpoint += 1
                    if completed_since_checkpoint >= CHECKPOINT_EVERY:
                        _checkpoint_save(database, output_path)
                        completed_since_checkpoint = 0

        # Deduplicate
        for dest_data in database["destinations"].values():
            dest_data["restaurants"] = self._deduplicate_by_name(dest_data["restaurants"])
            dest_data["attractions"] = self._deduplicate_by_name(dest_data["attractions"])
            dest_data["local_dishes"] = self._deduplicate_by_name(dest_data["local_dishes"])

        self._build_folder_coverage(database)

        # Reset review status to pending for any cities that were rebuilt
        affected_cities = {
            meta.get("destination", "")
            for rel_key, meta in database["_processed_files"].items()
            if rel_key in {str(fp.relative_to(self.library_path)) for fp in files_to_process}
        }
        review_status = database.get("_review_status", {})
        if review_status:
            for city in affected_cities:
                if city in review_status:
                    review_status[city] = {"status": "pending"}
            database["_review_status"] = review_status

        _checkpoint_save(database, output_path)

        console.print(f"\n[bold green]✓ Database saved to {output_path}[/bold green]")
        self._print_summary(database)
        return database

    def process_single_file(self, file_path: Path, destination: str, database: dict) -> bool:
        """Process one file and merge its data into database in-place. Returns True on success."""
        rel_key = str(file_path.relative_to(self.library_path))

        try:
            file_data = self._process_file(file_path)
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to process {rel_key}: {e}")
            return False

        if not file_data:
            return False

        file_mtime = os.path.getmtime(file_path)
        tracked_dests: set[str] = set()
        _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips"}

        for field in ("restaurants", "attractions", "hotels",
                      "local_dishes", "phrases", "safety_tips", "souvenirs",
                      "emergency_contacts", "connectivity_tips",
                      "transport_options", "health_tips"):
            for item in file_data.get(field) or []:
                if isinstance(item, dict):
                    item["_source_file"] = rel_key
                    item["_source_mtime"] = file_mtime
                    if field in _MULTI_CITY_FIELDS:
                        raw = item.get("cities") or [item.get("city", "")]
                        dests = [c.strip().title() for c in raw if c and c.strip()] or [destination]
                    else:
                        raw_city = item.get("city", "").strip()
                        dests = [raw_city.title() if raw_city else destination]
                else:
                    dests = [destination]

                for dest in dests:
                    if dest not in database["destinations"]:
                        database["destinations"][dest] = {
                            "restaurants": [], "attractions": [], "hotels": [],
                            "local_dishes": [], "phrases": [], "safety_tips": [],
                            "souvenirs": [], "emergency_contacts": [],
                            "connectivity_tips": [], "transport_options": [],
                            "health_tips": [], "source_files": [],
                        }

                    dest_data = database["destinations"][dest]
                    if dest not in tracked_dests:
                        if rel_key not in dest_data["source_files"]:
                            dest_data["source_files"].append(rel_key)
                        tracked_dests.add(dest)

                    dest_data[field].append(item)

        database["_processed_files"][rel_key] = {
            "mtime": file_mtime,
            "destination": destination,
            "covered_cities": file_data.get("covered_cities", []),
            "processed_at": datetime.now().isoformat(),
        }

        self._build_folder_coverage(database)
        return True

    def _process_file(self, file_path: Path) -> Optional[dict]:
        """Extract structured data from one DOCX or PDF file via AI."""
        try:
            if file_path.suffix.lower() == '.pdf':
                full_text = self._extract_text_from_pdf(file_path)
            else:
                full_text = self._extract_text_from_docx(file_path)
        except Exception as e:
            console.print(f"[dim]Text extraction failed for {file_path.name}: {e}[/dim]")
            return None

        full_text = _sanitize_text(full_text)

        if len(full_text) < 200:
            return None

        if len(full_text) <= SINGLE_PASS_LIMIT:
            result = self._call_and_parse(LIBRARY_EXTRACTION_PROMPT.format(text=full_text), file_path.name)
            return result

        # Multi-pass chunked extraction for large documents
        chunks = _split_into_chunks_shared(full_text)
        console.print(f"[dim]{file_path.name}: {len(full_text):,} chars → {len(chunks)} chunks[/dim]")

        chunk_results = []
        for i, chunk in enumerate(chunks):
            result = self._call_and_parse(
                LIBRARY_EXTRACTION_PROMPT.format(text=chunk),
                f"{file_path.name} chunk {i+1}/{len(chunks)}",
            )
            if result:
                chunk_results.append(result)

        if not chunk_results:
            console.print(f"[dim]AI extraction failed for {file_path.name}: all chunks failed[/dim]")
            return None

        if len(chunk_results) == 1:
            return chunk_results[0]

        return _merge_extraction_results_shared(chunk_results)

    def _call_and_parse(self, prompt: str, label: str) -> Optional[dict]:
        """Send prompt to AI and parse the JSON response."""
        result = _shared_call_and_parse(self.client, prompt, label)
        if result:
            _clean_entry_fees(result)
        return result

    def _extract_text_from_docx(self, docx_path: Path) -> str:
        doc = Document(docx_path)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        doc = fitz.open(pdf_path)
        text_parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(text_parts)

    def _build_folder_coverage(self, database: dict) -> None:
        """Build _folder_coverage by unioning covered_cities across all processed files per folder."""
        coverage: dict[str, set] = {}
        for meta in database["_processed_files"].values():
            folder = meta.get("destination", "")
            cities = meta.get("covered_cities", [])
            if folder:
                coverage.setdefault(folder, set()).update(c.strip() for c in cities if c.strip())
        database["_folder_coverage"] = {f: sorted(cities) for f, cities in coverage.items()}

    def _deduplicate_by_name(self, items: list) -> list:
        """Deduplicate items by name with recency-aware merging.

        - must_try_dishes: always unioned across all source files
        - all other fields: overwritten only if the incoming file is newer
        - source_files: accumulated list of every file the item appeared in
        """
        seen: dict[str, dict] = {}
        for item in items:
            name = item.get("name", "").lower().strip()
            if not name:
                continue
            src_file = item.get("_source_file")
            src_mtime = item.get("_source_mtime", 0)

            if name not in seen:
                seen[name] = item.copy()
                existing_sources = item.get("source_files") or []
                new_source = [src_file] if src_file else []
                seen[name]["source_files"] = list(dict.fromkeys(existing_sources + new_source))
            else:
                existing = seen[name]

                if src_file and src_file not in existing["source_files"]:
                    existing["source_files"].append(src_file)

                # Always union must_try_dishes
                existing_dishes = existing.get("must_try_dishes") or []
                new_dishes = item.get("must_try_dishes") or []
                merged = list(dict.fromkeys(existing_dishes + [d for d in new_dishes if d not in existing_dishes]))
                if merged:
                    existing["must_try_dishes"] = merged

                # Overwrite other fields only if incoming file is newer
                if src_mtime > existing.get("_source_mtime", 0):
                    for key, value in item.items():
                        if key in ("must_try_dishes", "_source_file", "_source_mtime", "source_files"):
                            continue
                        if value is not None:
                            existing[key] = value
                    existing["_source_mtime"] = src_mtime

        result = []
        for item in seen.values():
            item.pop("_source_file", None)
            item.pop("_source_mtime", None)
            result.append(item)
        return result

    def _print_summary(self, database: dict) -> None:
        console.print("\n[bold]Library Database Summary[/bold]\n")
        for dest, data in sorted(database["destinations"].items()):
            cities = database.get("_folder_coverage", {}).get(dest, [])
            console.print(f"  [cyan]{dest}[/cyan]")
            console.print(f"    Files:       {len(data['source_files'])}")
            console.print(f"    Restaurants: {len(data['restaurants'])}")
            console.print(f"    Attractions: {len(data['attractions'])}")
            console.print(f"    Cities:      {', '.join(cities[:5])}{'...' if len(cities) > 5 else ''}")
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
