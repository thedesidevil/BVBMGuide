import json
from pathlib import Path


COUNTRY_LEVEL_FIELDS = [
    "connectivity_tips",
    "safety_tips",
    "health_tips",
    "phrases",
    "emergency_contacts",
    "transport_options",
]


def extract_country_data(db_path: Path, folder_name: str, city_names: list[str]) -> dict:
    """Aggregate country-level data from city shards for a given folder/country."""
    country_data: dict[str, list] = {field: [] for field in COUNTRY_LEVEL_FIELDS}
    seen_tips: dict[str, set] = {field: set() for field in COUNTRY_LEVEL_FIELDS}

    for city in city_names:
        city_path = db_path / f"{city}.json"
        if not city_path.exists():
            continue
        with open(city_path, "r", encoding="utf-8") as f:
            shard = json.load(f)

        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key = item.get(key_field, "")
                    if key in seen_tips[field]:
                        continue
                    seen_tips[field].add(key)
                else:
                    item_key = json.dumps(item, sort_keys=True)
                    if item_key in seen_tips[field]:
                        continue
                    seen_tips[field].add(item_key)
                country_data[field].append(item)

    # Also check if the folder itself has a shard (e.g., "Japan.json" exists as both folder and shard)
    folder_path = db_path / f"{folder_name}.json"
    if folder_path.exists() and folder_name not in city_names:
        with open(folder_path, "r", encoding="utf-8") as f:
            shard = json.load(f)
        for field in COUNTRY_LEVEL_FIELDS:
            items = shard.get(field, [])
            for item in items:
                key_field = "tip" if "tip" in item else "phrase" if "phrase" in item else "english" if "english" in item else None
                if key_field:
                    key = item.get(key_field, "")
                    if key in seen_tips[field]:
                        continue
                    seen_tips[field].add(key)
                else:
                    item_key = json.dumps(item, sort_keys=True)
                    if item_key in seen_tips[field]:
                        continue
                    seen_tips[field].add(item_key)
                country_data[field].append(item)

    return country_data


def ensure_country_shards(db_path: Path) -> None:
    """Generate _country/ shards from city data if they don't exist yet."""
    country_dir = db_path / "_country"
    if country_dir.exists() and any(country_dir.glob("*.json")):
        return  # Already extracted

    country_dir.mkdir(exist_ok=True)
    index_path = db_path / "_index.json"
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    folder_coverage = index.get("_folder_coverage", {})
    for folder, cities in folder_coverage.items():
        data = extract_country_data(db_path, folder, cities)
        if any(data.values()):
            with open(country_dir / f"{folder}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
