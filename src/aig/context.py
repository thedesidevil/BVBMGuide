"""AIGContext — central data object for AIG generation."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.common.ai_provider import AIClient
from src.common.models import TripFacts
from src.library.builder import LibraryDatabase


class CityLibraryData(BaseModel):
    city: str
    restaurants: list = Field(default_factory=list)
    attractions: list = Field(default_factory=list)
    local_dishes: list = Field(default_factory=list)
    souvenirs: list = Field(default_factory=list)
    transport_options: list = Field(default_factory=list)
    emergency_contacts: list = Field(default_factory=list)
    phrases: list = Field(default_factory=list)
    safety_tips: list = Field(default_factory=list)
    connectivity_tips: list = Field(default_factory=list)
    health_tips: list = Field(default_factory=list)


@dataclass
class AIGContext:
    facts: TripFacts
    library: dict[str, CityLibraryData]          # city → data
    db_path: Path
    ai_client: AIClient
    hotel_coords: dict[str, tuple[float, float]] = field(default_factory=dict)


def build_context(
    facts: TripFacts,
    db_path: Path,
    ai_client: Any,
) -> AIGContext:
    db = LibraryDatabase(db_path)
    db.load()
    library: dict[str, CityLibraryData] = {}
    for city in _extract_cities(facts):
        raw = db.get_city_data(city)
        if raw:
            library[city] = CityLibraryData(
                city=city,
                **{k: raw.get(k, []) for k in CityLibraryData.model_fields if k != "city"},
            )
    return AIGContext(facts=facts, library=library, db_path=db_path, ai_client=ai_client)


def _extract_cities(facts: TripFacts) -> list[str]:
    cities: set[str] = set()
    for dest in facts.destinations:
        cities.add(dest.split("(")[0].split(",")[0].strip())
    for hotel in facts.hotels:
        cities.add(hotel.city)
    return sorted(cities)


def write_back_to_library(
    db_path: Path,
    city: str,
    field: str,
    value: list,
    updated_by: str,
) -> None:
    """Persist AI-generated content to the library DB with an audit entry."""
    city_file = db_path / f"{city}.json"
    if not city_file.exists():
        return
    data = json.loads(city_file.read_text(encoding="utf-8"))
    data[field] = value
    data.setdefault("_audit", []).append({
        "updated_by": updated_by,
        "field": field,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    city_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
