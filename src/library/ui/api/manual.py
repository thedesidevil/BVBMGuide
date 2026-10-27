"""Stamp hand-edited and hand-added library items so ingest never overwrites them."""

import json
from datetime import datetime, timezone

from ...ingest_core.identity import item_key

_PROVENANCE = ("_source_file", "_source_date", "_source_format", "_replaced_from")


def _content(item: dict) -> str:
    kept = {k: v for k, v in item.items()
            if k not in _PROVENANCE and not k.startswith("_manual")}
    return json.dumps(kept, sort_keys=True, default=str)


def _key(list_name: str, item: dict) -> str:
    return item_key(list_name, item) or str(item.get("name") or item.get("item") or "")


def stamp_item(item: dict, changed_by: str) -> None:
    item["_manual"] = True
    item["_manual_by"] = changed_by or "unknown"
    item["_manual_at"] = datetime.now(timezone.utc).isoformat()


def stamp_manual_edits(existing: dict, incoming: dict, changed_by: str) -> None:
    """Mutate ``incoming`` in place: flag added/edited items, keep stored flags and
    ``_conflicts`` the client did not send."""
    if "_conflicts" not in incoming and existing.get("_conflicts") is not None:
        incoming["_conflicts"] = existing["_conflicts"]

    for list_name, items in incoming.items():
        if not isinstance(items, list):
            continue
        old_items = existing.get(list_name)
        old_items = old_items if isinstance(old_items, list) else []
        old_dicts = [o for o in old_items if isinstance(o, dict)]
        by_key: dict[str, list[dict]] = {}
        for o in old_dicts:
            k = _key(list_name, o)
            if k:
                by_key.setdefault(k, []).append(o)
        old_contents = {_content(o) for o in old_dicts}

        for item in items:
            if not isinstance(item, dict):
                continue
            k = _key(list_name, item)
            matches = by_key.get(k, []) if k else []
            content = _content(item)
            same = next((o for o in matches if _content(o) == content), None)
            if same is None and not k and content in old_contents:
                same = next(o for o in old_dicts if _content(o) == content)
            if same is not None:
                if same.get("_manual"):
                    for mk, mv in same.items():
                        if mk.startswith("_manual") and mk not in item:
                            item[mk] = mv
                continue
            stamp_item(item, changed_by)
