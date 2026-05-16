from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend

MAX_AUDIT_ENTRIES = 200


class AuditService:
    """Manages the audit trail at _audit.json."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        data = self.backend.read_json("_audit.json")
        self._entries = data if isinstance(data, list) else []

    def _save(self):
        if len(self._entries) > MAX_AUDIT_ENTRIES:
            self._entries = self._entries[-MAX_AUDIT_ENTRIES:]
        self.backend.write_json("_audit.json", self._entries)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_deletion(
        self,
        category: str,
        city: str,
        item_name: str,
        reason: str,
        item_snapshot: dict,
        deleted_by: str = "unknown",
    ):
        entry = {
            "action": "delete",
            "category": category,
            "city": city,
            "item_name": item_name,
            "reason": reason,
            "changed_by": deleted_by,
            "changed_at": self._now(),
            "item_snapshot": item_snapshot,
        }
        self._entries.append(entry)
        self._save()

    def log_edit(
        self,
        category: str,
        city: str,
        item_name: str,
        changes: list[dict],
        changed_by: str = "unknown",
    ):
        entry = {
            "action": "edit",
            "category": category,
            "city": city,
            "item_name": item_name,
            "changes": changes,
            "changed_by": changed_by,
            "changed_at": self._now(),
        }
        self._entries.append(entry)
        self._save()

    def log_add(
        self,
        category: str,
        city: str,
        item_name: str,
        item_snapshot: dict,
        changed_by: str = "unknown",
    ):
        entry = {
            "action": "add",
            "category": category,
            "city": city,
            "item_name": item_name,
            "item_snapshot": item_snapshot,
            "changed_by": changed_by,
            "changed_at": self._now(),
        }
        self._entries.append(entry)
        self._save()

    def get_entries(self, limit: Optional[int] = None) -> list[dict]:
        entries = list(reversed(self._entries))
        if limit:
            return entries[:limit]
        return entries
