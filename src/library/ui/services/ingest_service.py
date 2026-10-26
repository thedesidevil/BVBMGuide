"""Ingest service: session management, classify, extract, and persist for the ingest wizard."""

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
        """Extract every non-excluded file with the shared ``extract_file``.

        ``Extraction.data`` is stored at the session's extracted key so the
        wizard's review step can show and edit it; ``persist`` cleans and merges it.
        """
        import tempfile

        from src.common.ai_provider import get_ai_client
        from src.library.ingest_core import extract as extract_mod

        client = get_ai_client()
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

            ext = entry.get("type", "pdf")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                extraction = extract_mod.extract_file(client, tmp_path)
                if extraction is None:
                    return file_id, "failed", {"error": "Extraction returned no data"}
                return file_id, "extracted", extraction.data
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
        """Clean and merge each reviewed extraction into the library via the ingest core.

        Per non-excluded file with an ``assigned_folder`` and extracted data:
        ``scan_file`` on the uploaded bytes gives the format and order date
        (``last_day`` or today), then ``clean_extraction`` and ``merge_extraction``
        (newer-wins, manual items protected) run with
        ``source_file = "<folder>/<filename>"``. The source file is copied into
        ``aig-library/<folder>/`` and the processed-files index and folder
        coverage are updated; the index is saved once at the end.

        Skipped (listed under ``skipped`` as ``(filename, reason)``, not
        recorded): v2-generated files (``bvbm_run_id`` property, reason
        ``v2_generated``) and files whose cleaned extraction has no cities and no
        items, such as a failed extraction stored as ``{"error": ...}`` (reason
        ``empty``).

        Each file is isolated: missing upload bytes or any exception while
        scanning, cleaning, merging or recording puts ``(filename, error)`` under
        ``failed`` and the next file is processed. The index is saved in a
        ``finally``. Staging is cleaned up only when no file failed, so failed
        uploads stay available for a retry.

        Returns ``persisted_files``, ``affected_cities`` (city shards the items
        were merged into), ``stats`` (summed ``MergeStats`` incl. ``by_city``),
        ``dropped`` (count of items removed by cleaning), ``skipped`` and
        ``failed``.
        """
        from dataclasses import asdict

        from src.library.ingest_core.merge import MergeStats
        from src.library.ui.services.db_service import LibraryDBService

        db_service = LibraryDBService(self.backend)
        files = session.get_files()
        persisted_count = 0
        dropped_count = 0
        total = MergeStats()
        skipped: list[tuple[str, str]] = []
        failed: list[tuple[str, str]] = []

        try:
            for file_id, entry in files.items():
                if entry.get("excluded"):
                    continue
                folder = entry.get("assigned_folder")
                if not folder:
                    continue

                data = self.backend.read_json(session.get_extracted_key(file_id))
                if not data:
                    continue

                filename = entry.get("filename") or f"{file_id}.{entry.get('type') or 'pdf'}"
                try:
                    outcome = self._persist_one(session, db_service, file_id, entry,
                                                folder, filename, data)
                except Exception as e:  # one bad file must not abort the others
                    failed.append((filename, f"{type(e).__name__}: {e}"))
                    continue
                if isinstance(outcome, str):
                    skipped.append((filename, outcome))
                    continue
                stats, dropped = outcome
                total += stats
                dropped_count += dropped
                persisted_count += 1
        finally:
            db_service.save_index()

        if not failed:
            session.cleanup()

        affected = {name for name in total.by_city if not name.startswith("_country/")}
        return {
            "persisted_files": persisted_count,
            "affected_cities": sorted(affected),
            "stats": asdict(total),
            "dropped": dropped_count,
            "skipped": skipped,
            "failed": failed,
        }

    def _persist_one(self, session: IngestSession, db_service, file_id: str, entry: dict,
                     folder: str, filename: str, data: dict):
        """Clean, merge and record one file. Returns ``(MergeStats, dropped_count)``
        or a skip reason string; raises on failure (the caller records it)."""
        import tempfile
        from datetime import date

        from src.library.ingest_core.clean import clean_extraction, is_v2_generated
        from src.library.ingest_core.merge import FileMeta, merge_extraction
        from src.library.ingest_core.ordering import scan_file
        from src.library.ingest_core.runner import has_content

        file_bytes = self.backend.read_bytes(session.get_upload_key(file_id))
        if not file_bytes:
            raise FileNotFoundError("uploaded file is missing or empty")

        suffix = Path(filename).suffix or f".{entry.get('type') or 'pdf'}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        try:
            if is_v2_generated(tmp_path):
                return "v2_generated"
            scan = scan_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        order_date = scan.last_day or date.today()

        cleaned, dropped = clean_extraction(data)
        if not has_content(cleaned):
            # nothing left after cleaning: do not record, so a later run can ingest it
            return "empty"
        rel_key = f"{folder}/{filename}"
        meta = FileMeta(source_file=rel_key, order_date=order_date, fmt=scan.fmt, folder=folder)
        stats = merge_extraction(db_service, cleaned, meta)

        # Copy source file to aig-library (only on local filesystem)
        if self.library_path:
            dest_dir = self.library_path / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / filename
            if not dest_file.exists():
                dest_file.write_bytes(file_bytes)

        covered = cleaned.get("covered_cities")
        covered = [c for c in covered if isinstance(c, str) and c.strip()] \
            if isinstance(covered, list) else []
        db_service.record_processed_file(rel_key, {
            "text_hash": scan.text_hash,
            "order_date": order_date.isoformat(),
            "fmt": scan.fmt,
            "folder": folder,
            "covered_cities": covered,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })
        db_service.add_folder_coverage(folder, covered)
        return stats, len(dropped)
