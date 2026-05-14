from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage import StorageBackend

COUNTRY_LEVEL_FIELDS = [
    "connectivity_tips",
    "safety_tips",
    "health_tips",
    "phrases",
    "emergency_contacts",
    "transport_options",
]


def extract_country_data(backend: 'StorageBackend', folder_name: str, city_names: list[str]) -> dict:
    """Aggregate country-level data from city shards for a given folder/country."""
    country_data: dict[str, list] = {field: [] for field in COUNTRY_LEVEL_FIELDS}
    seen_tips: dict[str, set] = {field: set() for field in COUNTRY_LEVEL_FIELDS}

    for city in city_names:
        shard = backend.read_json(f"{city}.json")
        if not shard:
            continue

        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key_val = (item.get(key_field) or "").strip().lower()
                    if key_val and key_val not in seen_tips[field]:
                        seen_tips[field].add(key_val)
                        country_data[field].append(item)
                else:
                    country_data[field].append(item)

    return country_data


def ensure_country_shards(backend: 'StorageBackend'):
    """Generate country-level shards from city data if they don't exist."""
    from .db_service import LibraryDBService

    db = LibraryDBService(backend)
    coverage = db.get_folder_coverage()

    for folder, cities in coverage.items():
        country_name = folder.replace("-", " ").title()
        existing = backend.read_json(f"_country/{country_name}.json")
        if existing:
            continue

        country_data = extract_country_data(backend, folder, cities)
        has_content = any(len(v) > 0 for v in country_data.values())
        if has_content:
            backend.write_json(f"_country/{country_name}.json", country_data)
