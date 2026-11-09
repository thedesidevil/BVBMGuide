"""Persistent user-confirmed place overrides (a Google Maps link the team pasted for a place Google could not match).

Stored as `_place_overrides.json` in the library folder; the library builder/ingester never touches it.
"""
import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from src.aigv2.models import Place
from src.aigv2.textnorm import fold_key

FILE_NAME = "_place_overrides.json"


def okey(name: str, city: str) -> str:
    return f"{fold_key(name)}|{fold_key(city)}"


class PlaceOverrides:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("overrides", {}), dict):
                return data.get("overrides", {})
        except (OSError, ValueError):
            pass
        # corrupt: treat as empty, but keep the bad file so a later write cannot silently destroy it
        try:
            shutil.copyfile(self.path, self.path.with_name(self.path.name + ".bak"))
        except OSError:
            pass
        return {}

    def all(self) -> dict[str, dict]:
        return self._load()

    def get(self, name: str, city: str) -> Optional[dict]:
        data = self._load()
        if not data:
            return None
        k = okey(name, city)
        if k in data:
            return data[k]
        city_k = fold_key(city)
        for e in data.values():  # the name Google shows for it also finds it
            if fold_key(e.get("google_name", "")) == fold_key(name) and fold_key(e.get("city", "")) == city_k:
                return e
        return None

    def put(self, name_asked: str, city: str, google_name: str, lat: float, lng: float, maps_url: str,
            cid: Optional[str] = None, place_id: Optional[str] = None, address: Optional[str] = None) -> dict:
        data = self._load()
        entry = {"name_asked": name_asked, "city": city, "google_name": google_name, "lat": lat, "lng": lng,
                 "cid": cid, "maps_url": maps_url, "place_id": place_id or None, "address": address or None,
                 "confirmed_by": "user", "added": date.today().isoformat()}
        data[okey(name_asked, city)] = entry
        self._write(data)
        return entry

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"overrides": data}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def place_from_override(entry: dict, query: str) -> Place:
    return Place(query=query, place_id=entry.get("place_id") or "", name=entry.get("google_name") or entry["name_asked"],
                 address=entry.get("address") or "", lat=entry["lat"], lng=entry["lng"], status="UNKNOWN", hours=None,
                 website=None, phone=None, maps_url=entry["maps_url"], fetched_at=datetime.now(timezone.utc),
                 match_ok=True, verify_note="Matched from a saved place link (team-confirmed)")
