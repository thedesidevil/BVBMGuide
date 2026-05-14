from datetime import datetime, timezone
from typing import Optional

from ..storage import StorageBackend


class LibraryDBService:
    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._index: dict = {}
        self._load_index()

    def _load_index(self):
        data = self.backend.read_json("_index.json")
        self._index = data if data else {}

    def _save_index(self):
        self.backend.write_json("_index.json", self._index)

    def get_folder_coverage(self) -> dict[str, list[str]]:
        return self._index.get("_folder_coverage", {})

    def get_review_status(self) -> dict[str, dict]:
        return self._index.get("_review_status", {})

    def set_review_status(self, name: str, status: str, reviewed_by: str = "unknown"):
        if "_review_status" not in self._index:
            self._index["_review_status"] = {}
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
        return self.backend.read_json(f"{city}.json")

    def save_city_data(self, city: str, data: dict):
        self.backend.write_json(f"{city}.json", data)

    def get_country_data(self, country: str) -> Optional[dict]:
        return self.backend.read_json(f"_country/{country}.json")

    def save_country_data(self, country: str, data: dict):
        self.backend.write_json(f"_country/{country}.json", data)

    def get_all_city_names(self) -> list[str]:
        all_keys = self.backend.list_keys("")
        names = []
        for key in sorted(all_keys):
            if "/" in key:
                continue
            if key.endswith(".json") and key not in ("_index.json", "_audit.json"):
                names.append(key[:-5])
        return names

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
