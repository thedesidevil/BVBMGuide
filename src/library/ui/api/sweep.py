from fastapi import APIRouter, Request, Query
from pydantic import BaseModel
from typing import Optional

from ..services.db_service import LibraryDBService

router = APIRouter()


@router.get("/sweep")
def get_sweep(
    request: Request,
    category: str = Query(..., description="e.g. restaurants, attractions"),
    field: Optional[str] = Query(None, description="e.g. vegetarian_friendly, hours"),
    filter: Optional[str] = Query(None, description="all, missing, unchecked, checked"),
):
    db = LibraryDBService(request.app.state.db_path)
    results = []

    all_cities = db.get_all_city_names()
    for city_name in all_cities:
        data = db.get_city_data(city_name)
        if not data:
            continue
        items = data.get(category, [])
        for idx, item in enumerate(items):
            if field and filter and filter != "all":
                value = item.get(field)
                if filter == "missing" and value not in (None, "", []):
                    continue
                if filter == "unchecked" and value is not False:
                    continue
                if filter == "checked" and value is not True:
                    continue

            results.append({
                "city": city_name,
                "index": idx,
                "item": item,
            })

    return {
        "category": category,
        "field": field,
        "filter": filter,
        "total": len(results),
        "items": results,
    }


class SweepSaveRequest(BaseModel):
    edits: list[dict]


@router.put("/sweep")
def save_sweep(request: Request, body: SweepSaveRequest):
    db = LibraryDBService(request.app.state.db_path)
    affected_cities: set[str] = set()

    for edit in body.edits:
        city = edit["city"]
        index = edit["index"]
        category = edit["category"]
        field_name = edit["field"]
        value = edit["value"]

        data = db.get_city_data(city)
        if not data:
            continue
        items = data.get(category, [])
        if index < 0 or index >= len(items):
            continue
        items[index][field_name] = value
        db.save_city_data(city, data)
        affected_cities.add(city)

    for city in affected_cities:
        db.set_review_status(city, "in_progress")

    return {"status": "saved", "affected_cities": len(affected_cities)}
