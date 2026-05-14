from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend


class AuditService:
    """Manages the deletion audit trail at _audit.json."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        data = self.backend.read_json("_audit.json")
        self._entries = data if isinstance(data, list) else []

    def _save(self):
        self.backend.write_json("_audit.json", self._entries)

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
            "deleted_by": deleted_by,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "item_snapshot": item_snapshot,
        }
        self._entries.append(entry)
        self._save()

    def get_entries(self, limit: Optional[int] = None) -> list[dict]:
        entries = list(reversed(self._entries))
        if limit:
            return entries[:limit]
        return entries
