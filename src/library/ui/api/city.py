import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..services.db_service import LibraryDBService
from ..services.audit_service import AuditService

router = APIRouter()

AUDITED_CATEGORIES = ("restaurants", "attractions", "hotels", "local_dishes", "souvenirs")


class DeleteItemRequest(BaseModel):
    reason: str
    deleted_by: str = "unknown"


def _item_key(item: dict) -> str:
    return item.get("name") or item.get("item") or ""


def _diff_city(existing: dict, incoming: dict, changed_by: str, city: str, audit: AuditService):
    """Compare existing vs incoming city data and log edits/additions."""
    for category in AUDITED_CATEGORIES:
        orig_items = existing.get(category, [])
        new_items = incoming.get(category, [])

        orig_by_key = {_item_key(item): item for item in orig_items}
        new_by_key = {_item_key(item): item for item in new_items}

        # Detect edits (items present in both, matched by name)
        for key, new_item in new_by_key.items():
            if not key or key not in orig_by_key:
                continue
            orig_item = orig_by_key[key]
            changes = []
            for field in set(list(orig_item.keys()) + list(new_item.keys())):
                if field.startswith("_"):
                    continue
                old_val = orig_item.get(field)
                new_val = new_item.get(field)
                if json.dumps(old_val, sort_keys=True, default=str) != json.dumps(new_val, sort_keys=True, default=str):
                    changes.append({"field": field, "old": old_val, "new": new_val})
            if changes:
                audit.log_edit(
                    category=category,
                    city=city,
                    item_name=key,
                    changes=changes,
                    changed_by=changed_by,
                )

        # Detect additions (items in new but not in original)
        for key, new_item in new_by_key.items():
            if key and key in orig_by_key:
                continue
            item_name = key or f"item_{new_items.index(new_item)}"
            audit.log_add(
                category=category,
                city=city,
                item_name=item_name,
                item_snapshot=new_item,
                changed_by=changed_by,
            )


@router.get("/city/{name}")
def get_city(name: str, request: Request):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    return data


@router.put("/city/{name}")
def save_city(name: str, request: Request, body: dict):
    db = LibraryDBService(request.app.state.storage_backend)
    existing = db.get_city_data(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")

    changed_by = body.pop("changed_by", "unknown")
    audit = AuditService(request.app.state.storage_backend)
    _diff_city(existing, body, changed_by, name, audit)

    db.save_city_data(name, body)
    db.set_review_status(name, "in_progress")
    return {"status": "saved"}


@router.delete("/city/{name}/{category}/{index}")
def delete_item(name: str, category: str, index: int, request: Request, body: DeleteItemRequest):
    db = LibraryDBService(request.app.state.storage_backend)
    data = db.get_city_data(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"City '{name}' not found")
    items = data.get(category, [])
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail=f"Item index {index} out of range")

    deleted_item = items.pop(index)
    db.save_city_data(name, data)

    audit = AuditService(request.app.state.storage_backend)
    audit.log_deletion(
        category=category,
        city=name,
        item_name=deleted_item.get("name", "unknown"),
        reason=body.reason,
        item_snapshot=deleted_item,
        deleted_by=body.deleted_by,
    )
    db.set_review_status(name, "in_progress")
    return {"status": "deleted"}
