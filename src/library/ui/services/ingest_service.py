"""Ingest service: session management, classify, extract, and persist for the ingest wizard."""

import json
import shutil
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class IngestSession:
    """Manages one ingest session's staging directory."""

    def __init__(self, session_id: str, staging_root: Path):
        self.session_id = session_id
        self.root = staging_root / session_id
        self.uploads_dir = self.root / "uploads"
        self.extracted_dir = self.root / "extracted"
        self.meta_path = self.root / "meta.json"

    def ensure_dirs(self):
        """Create uploads/ and extracted/ subdirs."""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)

    def load_meta(self) -> dict:
        """Read meta.json; return default skeleton if missing."""
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "session_id": self.session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }

    def save_meta(self, meta: dict):
        """Write meta dict to meta.json."""
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def add_file(self, file_id: str, filename: str, size: int, file_type: str) -> dict:
        """Add a file entry with state='uploaded' and persist."""
        meta = self.load_meta()
        entry = {
            "file_id": file_id,
            "filename": filename,
            "size": size,
            "type": file_type,
            "state": "uploaded",
        }
        meta["files"][file_id] = entry
        self.save_meta(meta)
        return entry

    def remove_file(self, file_id: str):
        """Remove file entry from meta and delete physical files."""
        meta = self.load_meta()
        entry = meta["files"].pop(file_id, None)
        self.save_meta(meta)

        if entry:
            # Remove uploaded file
            upload_path = self.get_upload_path(file_id)
            if upload_path.exists():
                upload_path.unlink()

        # Remove extracted file if present
        extracted_path = self.get_extracted_path(file_id)
        if extracted_path.exists():
            extracted_path.unlink()

    def get_files(self) -> dict:
        """Return the files dict from meta."""
        return self.load_meta().get("files", {})

    def get_file(self, file_id: str) -> Optional[dict]:
        """Return a single file entry, or None if not found."""
        return self.get_files().get(file_id)

    def update_file(self, file_id: str, updates: dict):
        """Merge updates dict into the file entry and persist."""
        meta = self.load_meta()
        if file_id in meta["files"]:
            meta["files"][file_id].update(updates)
            self.save_meta(meta)

    def get_upload_path(self, file_id: str) -> Path:
        """Return Path to uploads/{file_id}.{ext}."""
        entry = self.get_file(file_id)
        if entry:
            return self.uploads_dir / f"{file_id}{self._ext(entry)}"
        # Fallback: check for any matching file
        for candidate in self.uploads_dir.glob(f"{file_id}.*"):
            return candidate
        return self.uploads_dir / file_id

    def get_extracted_path(self, file_id: str) -> Path:
        """Return Path to extracted/{file_id}.json."""
        return self.extracted_dir / f"{file_id}.json"

    def cleanup(self):
        """Remove the entire session staging directory."""
        if self.root.exists():
            shutil.rmtree(self.root)

    def _ext(self, entry: dict) -> str:
        """Return '.{type}' extension from entry dict (e.g. '.pdf', '.docx')."""
        file_type = entry.get("type", "")
        if not file_type:
            return ""
        if not file_type.startswith("."):
            return f".{file_type}"
        return file_type


class IngestService:
    """Orchestrates upload, classify, extract, and persist for the ingest wizard."""

    # Fields that are city-level (item has a "city" key)
    _CITY_FIELDS = {"restaurants", "attractions", "hotels", "local_dishes", "souvenirs"}

    # Fields that are multi-city (item has a "cities" list)
    _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips", "phrases",
                          "emergency_contacts", "transport_options"}

    def __init__(self, db_path: str | Path, library_path: str | Path):
        self.db_path = Path(db_path)
        self.library_path = Path(library_path)
        self._staging_root = self.db_path / "_staging"
        self._staging_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self) -> IngestSession:
        """Create a new UUID session with staging directories."""
        session_id = str(uuid.uuid4())
        session = IngestSession(session_id, self._staging_root)
        session.ensure_dirs()
        meta = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        session.save_meta(meta)
        return session

    def get_session(self, session_id: str) -> Optional[IngestSession]:
        """Load an existing session, or return None if it doesn't exist."""
        session = IngestSession(session_id, self._staging_root)
        if not session.meta_path.exists():
            return None
        return session

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def save_upload(self, session: IngestSession, filename: str, content: bytes) -> list[dict]:
        """Save file bytes to staging. Handles ZIP extraction.

        Returns a list of file entry dicts (one per file saved, multiple for ZIPs).
        """
        suffix = Path(filename).suffix.lower()

        if suffix == ".zip":
            return self._handle_zip(session, filename, content)

        if suffix not in (".pdf", ".docx"):
            raise ValueError(f"Unsupported file type: {suffix}")

        file_id = str(uuid.uuid4())
        file_type = suffix.lstrip(".")
        entry = session.add_file(file_id, filename, len(content), file_type)

        dest = session.get_upload_path(file_id)
        with open(dest, "wb") as f:
            f.write(content)

        return [entry]

    def _handle_zip(self, session: IngestSession, zip_filename: str, content: bytes) -> list[dict]:
        """Extract pdf/docx from a ZIP archive; skip __MACOSX entries."""
        entries = []

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.infolist():
                    name = member.filename
                    # Skip Mac metadata directories
                    if "__MACOSX" in name or name.startswith("."):
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix not in (".pdf", ".docx"):
                        continue

                    file_id = str(uuid.uuid4())
                    file_type = suffix.lstrip(".")
                    inner_filename = Path(name).name
                    file_bytes = zf.read(member)

                    entry = session.add_file(file_id, inner_filename, len(file_bytes), file_type)

                    dest = session.get_upload_path(file_id)
                    with open(dest, "wb") as f:
                        f.write(file_bytes)

                    entries.append(entry)
        finally:
            tmp_path.unlink(missing_ok=True)

        return entries

    # ------------------------------------------------------------------
    # Classify
    # ------------------------------------------------------------------

    def classify_all(self, session: IngestSession) -> dict:
        """Classify each non-excluded file using LibraryIngester.

        Returns a mapping of file_id -> folder name.
        """
        from src.library.ingester import LibraryIngester

        existing_folders = sorted(
            f.name for f in self.library_path.iterdir() if f.is_dir()
        ) if self.library_path.exists() else []

        ingester = LibraryIngester(library_path=self.library_path)

        results: dict[str, str] = {}
        files = session.get_files()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue

            upload_path = session.get_upload_path(file_id)
            if not upload_path.exists():
                continue

            try:
                folder = ingester._classify_file(upload_path, existing_folders)
                if folder and folder not in existing_folders:
                    existing_folders.append(folder)
            except Exception:
                folder = None

            session.update_file(file_id, {
                "state": "classified",
                "folder": folder,
            })
            results[file_id] = folder

        return results

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------

    def extract_all(self, session: IngestSession, workers: int = 5) -> dict:
        """Run AI extraction on each classified file using LibraryBuilder.

        Saves results to extracted/{file_id}.json.
        Returns a mapping of file_id -> "extracted" | "failed".
        """
        from src.library.builder import LibraryBuilder

        builder = LibraryBuilder(library_path=self.library_path)

        files = session.get_files()
        candidates = {
            fid: entry
            for fid, entry in files.items()
            if not entry.get("excluded") and session.get_upload_path(fid).exists()
        }

        results: dict[str, str] = {}

        def _extract_one(file_id: str, entry: dict) -> tuple[str, str, Optional[dict]]:
            upload_path = session.get_upload_path(file_id)
            try:
                data = builder._process_file(upload_path)
                return file_id, "extracted", data
            except Exception as e:
                return file_id, "failed", {"error": str(e)}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_extract_one, fid, entry): fid
                for fid, entry in candidates.items()
            }

            for future in as_completed(future_map):
                file_id, status, data = future.result()
                extracted_path = session.get_extracted_path(file_id)

                if status == "extracted" and data:
                    with open(extracted_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    session.update_file(file_id, {"state": "extracted"})
                else:
                    # Write error info to extracted path for inspection
                    if data:
                        with open(extracted_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    session.update_file(file_id, {"state": "failed"})

                results[file_id] = status

        return results

    def get_extraction_status(self, session: IngestSession) -> dict:
        """Return per-file status with extracted data if available."""
        files = session.get_files()
        status: dict[str, dict] = {}

        for file_id, entry in files.items():
            record: dict = {
                "file_id": file_id,
                "filename": entry.get("filename"),
                "state": entry.get("state"),
                "folder": entry.get("folder"),
            }

            extracted_path = session.get_extracted_path(file_id)
            if extracted_path.exists():
                try:
                    with open(extracted_path, "r", encoding="utf-8") as f:
                        record["data"] = json.load(f)
                except Exception:
                    record["data"] = None

            status[file_id] = record

        return status

    def save_extracted_edits(self, session: IngestSession, file_id: str, data: dict):
        """Overwrite extracted JSON for a file with user-edited data."""
        extracted_path = session.get_extracted_path(file_id)
        with open(extracted_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def persist(self, session: IngestSession):
        """Merge extracted data into city shards, move files to aig-library, clean up."""
        from src.library.ui.services.db_service import LibraryDBService

        db_service = LibraryDBService(self.db_path)
        files = session.get_files()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue

            folder = entry.get("folder")
            if not folder:
                continue

            extracted_path = session.get_extracted_path(file_id)
            if not extracted_path.exists():
                continue

            try:
                with open(extracted_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            # Merge city-level fields
            for field in self._CITY_FIELDS:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    city_raw = item.get("city", "").strip()
                    city = city_raw.title() if city_raw else folder

                    city_data = db_service.get_city_data(city)
                    if city_data is None:
                        city_data = self._empty_city_shard()

                    field_key = "item" if field == "souvenirs" else "name"
                    if not self._is_duplicate(city_data.get(field, []), item, field_key):
                        city_data.setdefault(field, []).append(item)

                    db_service.save_city_data(city, city_data)
                    db_service.set_review_status(city, "pending")

            # Merge multi-city fields
            for field in self._MULTI_CITY_FIELDS:
                for item in data.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    raw_cities = item.get("cities") or []
                    if not raw_cities:
                        raw_cities = [folder]

                    for city_raw in raw_cities:
                        city = city_raw.strip().title() if city_raw.strip() else folder

                        city_data = db_service.get_city_data(city)
                        if city_data is None:
                            city_data = self._empty_city_shard()

                        city_data.setdefault(field, []).append(item)
                        db_service.save_city_data(city, city_data)
                        db_service.set_review_status(city, "pending")

            # Move source file to aig-library/{folder}/
            upload_path = session.get_upload_path(file_id)
            if upload_path.exists():
                dest_dir = self.library_path / folder
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / entry.get("filename", upload_path.name)
                if not dest_file.exists():
                    shutil.move(str(upload_path), dest_file)

        # Clean up staging
        session.cleanup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_city_shard(self) -> dict:
        """Return a template city shard with all empty lists."""
        return {
            "restaurants": [],
            "attractions": [],
            "hotels": [],
            "local_dishes": [],
            "souvenirs": [],
            "phrases": [],
            "safety_tips": [],
            "connectivity_tips": [],
            "health_tips": [],
            "emergency_contacts": [],
            "transport_options": [],
            "source_files": [],
        }

    def _is_duplicate(self, existing_items: list, new_item: dict, field: str = "name") -> bool:
        """Check if new_item already exists in the list by matching the given field key."""
        new_val = (new_item.get(field) or "").strip().lower()
        if not new_val:
            return False
        for item in existing_items:
            if isinstance(item, dict):
                existing_val = (item.get(field) or "").strip().lower()
                if existing_val == new_val:
                    return True
        return False
