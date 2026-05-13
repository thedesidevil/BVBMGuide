import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditService:
    """Manages the deletion audit trail at library_db/_audit.json."""

    def __init__(self, db_path: str | Path):
        self.audit_path = Path(db_path) / "_audit.json"
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        if self.audit_path.exists():
            with open(self.audit_path, "r", encoding="utf-8") as f:
                self._entries = json.load(f)
        else:
            self._entries = []

    def _save(self):
        with open(self.audit_path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

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
        entries = list(reversed(self._entries))  # newest first
        if limit:
            return entries[:limit]
        return entries
