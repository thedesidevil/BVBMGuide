"""Ingest service: session management, classify, extract, and persist for the ingest wizard."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..storage import StorageBackend


class IngestSession:
    """Manages one ingest session's staging data via StorageBackend."""

    def __init__(self, session_id: str, backend: 'StorageBackend'):
        self.session_id = session_id
        self.backend = backend
        self._prefix = f"_staging/{session_id}"

    def _key(self, subpath: str) -> str:
        return f"{self._prefix}/{subpath}"

    def load_meta(self) -> dict:
        data = self.backend.read_json(self._key("meta.json"))
        if data:
            return data
        return {
            "session_id": self.session_id,
            "created_at": "",
            "files": {},
        }

    def save_meta(self, meta: dict):
        self.backend.write_json(self._key("meta.json"), meta)

    def add_file(self, file_id: str, filename: str, size: int, file_type: str) -> dict:
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
        meta = self.load_meta()
        entry = meta["files"].pop(file_id, None)
        self.save_meta(meta)
        if entry:
            self.backend.delete(self._key(f"uploads/{file_id}{self._ext(entry)}"))
        self.backend.delete(self._key(f"extracted/{file_id}.json"))

    def get_files(self) -> dict:
        return self.load_meta().get("files", {})

    def get_file(self, file_id: str) -> Optional[dict]:
        return self.get_files().get(file_id)

    def update_file(self, file_id: str, updates: dict):
        meta = self.load_meta()
        if file_id in meta["files"]:
            meta["files"][file_id].update(updates)
            self.save_meta(meta)

    def get_upload_key(self, file_id: str) -> str:
        """Return the storage key for an uploaded file."""
        entry = self.get_file(file_id)
        ext = self._ext(entry) if entry else ""
        return self._key(f"uploads/{file_id}{ext}")

    def get_extracted_key(self, file_id: str) -> str:
        """Return the storage key for extracted JSON."""
        return self._key(f"extracted/{file_id}.json")

    def cleanup(self):
        """Remove all staging data for this session."""
        if hasattr(self.backend, "delete_prefix"):
            self.backend.delete_prefix(self._prefix + "/")
        else:
            keys = self.backend.list_keys(self._prefix + "/")
            for key in keys:
                self.backend.delete(key)

    def _ext(self, entry: dict) -> str:
        file_type = entry.get("type", "") if entry else ""
        if not file_type:
            return ""
        if not file_type.startswith("."):
            return f".{file_type}"
        return file_type


class IngestService:
    """Orchestrates upload, classify, extract, and persist for the ingest wizard."""

    _CITY_FIELDS = {"restaurants", "attractions", "hotels", "local_dishes", "souvenirs"}
    _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips", "phrases",
                          "emergency_contacts", "transport_options"}

    def __init__(self, backend: 'StorageBackend', library_path: Optional[Path] = None):
        self.backend = backend
        self.library_path = library_path

    def create_session(self) -> IngestSession:
        session_id = str(uuid.uuid4())
        session = IngestSession(session_id, self.backend)
        meta = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        session.save_meta(meta)
        return session

    def get_session(self, session_id: str) -> Optional[IngestSession]:
        session = IngestSession(session_id, self.backend)
        if not self.backend.exists(session._key("meta.json")):
            return None
        return session

    def save_upload(self, session: IngestSession, filename: str, content: bytes) -> list[dict]:
        suffix = Path(filename).suffix.lower()

        if suffix == ".zip":
            return self._handle_zip(session, filename, content)

        if suffix not in (".pdf", ".docx"):
            raise ValueError(f"Unsupported file type: {suffix}")

        file_id = str(uuid.uuid4())
        file_type = suffix.lstrip(".")
        entry = session.add_file(file_id, filename, len(content), file_type)
        self.backend.write_bytes(session.get_upload_key(file_id), content)
        return [entry]

    def _handle_zip(self, session: IngestSession, zip_filename: str, content: bytes) -> list[dict]:
        import tempfile
        import zipfile

        entries = []
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                for member in zf.infolist():
                    name = member.filename
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
                    self.backend.write_bytes(session.get_upload_key(file_id), file_bytes)
                    entries.append(entry)
        finally:
            tmp_path.unlink(missing_ok=True)

        return entries

    def classify_all(self, session: IngestSession) -> dict:
        from src.library.ingester import LibraryIngester

        existing_folders = sorted(
            f.name for f in self.library_path.iterdir() if f.is_dir()
        ) if self.library_path and self.library_path.exists() else []

        ingester = LibraryIngester(library_path=self.library_path)
        results: dict[str, str] = {}
        files = session.get_files()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue

            file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
            if not file_bytes:
                continue

            import tempfile
            ext = entry.get("type", "pdf")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                folder = ingester._classify_file(tmp_path, existing_folders)
                if folder and folder not in existing_folders:
                    existing_folders.append(folder)
            except Exception:
                folder = None
            finally:
                tmp_path.unlink(missing_ok=True)

            session.update_file(file_id, {
                "state": "classified",
                "assigned_folder": folder,
                "is_new_folder": folder not in existing_folders if folder else False,
            })
            results[file_id] = folder

        return results

    def extract_all(self, session: IngestSession, workers: int = 5) -> dict:
        from src.library.builder import LibraryBuilder

        builder = LibraryBuilder(library_path=self.library_path)
        files = session.get_files()
        candidates = {
            fid: entry for fid, entry in files.items()
            if not entry.get("excluded")
        }

        results: dict[str, str] = {}

        def _extract_one(file_id: str, entry: dict) -> tuple[str, str, Optional[dict]]:
            file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
            if not file_bytes:
                return file_id, "failed", {"error": "File not found in storage"}

            import tempfile
            ext = entry.get("type", "pdf")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                data = builder._process_file(tmp_path)
                return file_id, "extracted", data
            except Exception as e:
                return file_id, "failed", {"error": str(e)}
            finally:
                tmp_path.unlink(missing_ok=True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_extract_one, fid, entry): fid
                for fid, entry in candidates.items()
            }

            for future in as_completed(future_map):
                file_id, status, data = future.result()

                if status == "extracted" and data:
                    self.backend.write_json(session.get_extracted_key(file_id), data)
                    session.update_file(file_id, {"state": "extracted"})
                else:
                    if data:
                        self.backend.write_json(session.get_extracted_key(file_id), data)
                    session.update_file(file_id, {"state": "failed"})

                results[file_id] = status

        return results

    def get_extraction_status(self, session: IngestSession) -> dict:
        files = session.get_files()
        status: dict[str, dict] = {}

        for file_id, entry in files.items():
            record: dict = {
                "file_id": file_id,
                "filename": entry.get("filename"),
                "state": entry.get("state"),
                "assigned_folder": entry.get("assigned_folder"),
            }
            data = self.backend.read_json(session.get_extracted_key(file_id))
            record["data"] = data
            status[file_id] = record

        return status

    def save_extracted_edits(self, session: IngestSession, file_id: str, data: dict):
        self.backend.write_json(session.get_extracted_key(file_id), data)

    def persist(self, session: IngestSession) -> dict:
        from src.library.ui.services.db_service import LibraryDBService

        db_service = LibraryDBService(self.backend)
        files = session.get_files()
        persisted_count = 0
        affected_cities: set[str] = set()

        for file_id, entry in files.items():
            if entry.get("excluded"):
                continue
            folder = entry.get("assigned_folder")
            if not folder:
                continue

            data = self.backend.read_json(session.get_extracted_key(file_id))
            if not data:
                continue

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
                    affected_cities.add(city)

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
                        affected_cities.add(city)

            # Move source file to aig-library (only on local filesystem)
            if self.library_path:
                file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
                if file_bytes:
                    dest_dir = self.library_path / folder
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest_file = dest_dir / entry.get("filename", f"{file_id}.pdf")
                    if not dest_file.exists():
                        dest_file.write_bytes(file_bytes)

            rel_key = f"{folder}/{entry.get('filename', '')}"
            covered = data.get("covered_cities", [])
            db_service._index.setdefault("_processed_files", {})[rel_key] = {
                "mtime": datetime.now(timezone.utc).timestamp(),
                "destination": folder,
                "covered_cities": covered,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            folder_coverage = db_service._index.setdefault("_folder_coverage", {})
            existing_cities = folder_coverage.get(folder, [])
            for city in covered:
                if city not in existing_cities:
                    existing_cities.append(city)
            folder_coverage[folder] = existing_cities

            persisted_count += 1

        db_service._save_index()
        session.cleanup()

        return {
            "persisted_files": persisted_count,
            "affected_cities": sorted(affected_cities),
        }

    def _empty_city_shard(self) -> dict:
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
        new_val = (new_item.get(field) or "").strip().lower()
        if not new_val:
            return False
        for item in existing_items:
            if isinstance(item, dict):
                existing_val = (item.get(field) or "").strip().lower()
                if existing_val == new_val:
                    return True
        return False
