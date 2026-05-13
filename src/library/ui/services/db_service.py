import json
from pathlib import Path
from typing import Optional


class LibraryDBService:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._index: dict = {}
        self._load_index()

    def _load_index(self):
        index_path = self.db_path / "_index.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                self._index = json.load(f)

    def _save_index(self):
        index_path = self.db_path / "_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def get_folder_coverage(self) -> dict[str, list[str]]:
        return self._index.get("_folder_coverage", {})

    def get_review_status(self) -> dict[str, dict]:
        return self._index.get("_review_status", {})

    def set_review_status(self, name: str, status: str, reviewed_by: str = "unknown"):
        if "_review_status" not in self._index:
            self._index["_review_status"] = {}
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if status == "reviewed":
            self._index["_review_status"][name] = {
                "status": "reviewed",
                "reviewed_at": now,
                "reviewed_by": reviewed_by,
            }
        elif status == "in_progress":
            self._index["_review_status"][name] = {
                "status": "in_progress",
                "last_edited": now,
            }
        else:
            self._index["_review_status"][name] = {"status": "pending"}
        self._save_index()

    def get_city_data(self, city: str) -> Optional[dict]:
        city_path = self.db_path / f"{city}.json"
        if not city_path.exists():
            return None
        with open(city_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_city_data(self, city: str, data: dict):
        city_path = self.db_path / f"{city}.json"
        with open(city_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_country_data(self, country: str) -> Optional[dict]:
        country_path = self.db_path / "_country" / f"{country}.json"
        if not country_path.exists():
            return None
        with open(country_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_country_data(self, country: str, data: dict):
        country_dir = self.db_path / "_country"
        country_dir.mkdir(exist_ok=True)
        country_path = country_dir / f"{country}.json"
        with open(country_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_all_city_names(self) -> list[str]:
        return [
            f.stem for f in sorted(self.db_path.glob("*.json"))
            if f.name not in ("_index.json", "_audit.json")
        ]

    def get_tree(self) -> dict:
        coverage = self.get_folder_coverage()
        review_status = self.get_review_status()
        existing_shards = set(self.get_all_city_names())

        tree = {}
        for folder, cities in sorted(coverage.items()):
            city_nodes = []
            for city in sorted(cities):
                if city in existing_shards:
                    shard = self.get_city_data(city)
                    restaurant_count = len(shard.get("restaurants", [])) if shard else 0
                    city_nodes.append({
                        "name": city,
                        "status": review_status.get(city, {}).get("status", "pending"),
                        "restaurant_count": restaurant_count,
                    })
            tree[folder] = {
                "cities": city_nodes,
                "status": review_status.get(folder, {}).get("status", "pending"),
            }

        return tree
