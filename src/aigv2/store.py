import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from pydantic import BaseModel

from src.aigv2.config import Settings
from src.aigv2.models import Place
from src.aigv2.textnorm import fold_key
from src.library.ui.storage import LocalStorageBackend, StorageBackend

_RUNS = "runs/"
_RUN_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")


class RunStore:
    def __init__(self, backend: StorageBackend, run_id: str):
        if not _RUN_ID.fullmatch(run_id or "") or ".." in run_id:
            raise ValueError(f"invalid run id {run_id!r}: use letters, digits, '-', '_' and '.' only")
        self.backend = backend
        self.run_id = run_id

    @classmethod
    def create(cls, backend: StorageBackend) -> "RunStore":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return cls(backend, f"{stamp}-{secrets.token_hex(3)}")

    def _key(self, name: str) -> str:
        return f"{_RUNS}{self.run_id}/{name}"

    def save_json(self, name: str, data: Union[dict, BaseModel]) -> None:
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        self.backend.write_json(self._key(name), data)

    def load_json(self, name: str) -> Optional[dict]:
        return self.backend.read_json(self._key(name))

    def save_bytes(self, name: str, data: bytes) -> None:
        self.backend.write_bytes(self._key(name), data)

    def load_bytes(self, name: str) -> Optional[bytes]:
        return self.backend.read_bytes(self._key(name))

    def has(self, name: str) -> bool:
        return self.backend.exists(self._key(name))

    def delete(self, name: str) -> None:
        self.backend.delete(self._key(name))

    def names(self) -> list[str]:
        prefix = self._key("")
        return sorted(k.replace("\\", "/")[len(prefix):] for k in self.backend.list_keys(prefix))

    def key(self, name: str) -> str:
        return self._key(name)

    @staticmethod
    def list_runs(backend: StorageBackend) -> list[str]:
        ids = {k[len(_RUNS):].split("/", 1)[0] for k in backend.list_keys(_RUNS)}
        return sorted((i for i in ids if i), reverse=True)


class PlaceCache:
    """Disk cache of place lookups. Keys are accent/case-folded (textnorm.fold_key); entries written before folding
    existed live under the sha1 of the raw key and are still read as a fallback."""

    def __init__(self, backend: StorageBackend, max_age_days: int, negative_days: int = 7):
        self.backend = backend
        self.max_age = timedelta(days=max_age_days)
        self.negative_age = timedelta(days=negative_days)

    @staticmethod
    def _key(key: str) -> str:
        return f"cache/places/{hashlib.sha1(fold_key(key).encode('utf-8')).hexdigest()}.json"

    @staticmethod
    def _legacy_key(key: str) -> str:
        return f"cache/places/{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"

    def _read(self, path: str) -> Optional[Place]:
        try:
            raw = self.backend.read_json(path)
            if raw is None:
                return None
            place = Place.model_validate(raw)
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        fetched = place.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > self.max_age:
            return None
        return place

    def get(self, key: str) -> Optional[Place]:
        place = self._read(self._key(key))
        if place is None and self._legacy_key(key) != self._key(key):
            place = self._read(self._legacy_key(key))
        return place

    def put(self, key: str, place: Place) -> None:
        self.backend.write_json(self._key(key), place.model_dump(mode="json"))

    @staticmethod
    def _neg_key(key: str) -> str:
        return f"cache/places_nomatch/{hashlib.sha1(fold_key(key).encode('utf-8')).hexdigest()}.json"

    def is_no_match(self, key: str) -> bool:
        """True when a clean zero-result answer for this key was stored within the last negative_days."""
        try:
            raw = self.backend.read_json(self._neg_key(key))
            if not isinstance(raw, dict) or raw.get("no_match") is not True:
                return False
            fetched = datetime.fromisoformat(raw["fetched_at"])
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - fetched <= self.negative_age

    def put_no_match(self, key: str) -> None:
        """Remember that Google cleanly answered with nothing usable; callers must never call this for failures."""
        self.backend.write_json(self._neg_key(key), {"no_match": True,
                                                     "fetched_at": datetime.now(timezone.utc).isoformat()})


class RouteCache:
    """Disk cache of single route-matrix elements (minutes between two points); failed lookups are never stored."""

    def __init__(self, backend: StorageBackend, max_age_days: int):
        self.backend = backend
        self.max_age = timedelta(days=max_age_days)

    @staticmethod
    def _key(key: str) -> str:
        return f"cache/routes/{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"

    def get(self, key: str) -> Optional[int]:
        try:
            raw = self.backend.read_json(self._key(key))
            if not isinstance(raw, dict) or not isinstance(raw.get("minutes"), int):
                return None
            fetched = datetime.fromisoformat(raw["fetched_at"])
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > self.max_age:
            return None
        return raw["minutes"]

    def put(self, key: str, minutes: int) -> None:
        self.backend.write_json(self._key(key), {"minutes": minutes,
                                                 "fetched_at": datetime.now(timezone.utc).isoformat()})


class NearbyCache:
    """Disk cache of whole nearby-search answers (lists of places) for a point, type set and radius."""

    def __init__(self, backend: StorageBackend, max_age_days: int):
        self.backend = backend
        self.max_age = timedelta(days=max_age_days)

    @staticmethod
    def _key(key: str) -> str:
        return f"cache/nearby/{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"

    def get(self, key: str) -> Optional[list[Place]]:
        try:
            raw = self.backend.read_json(self._key(key))
            if not isinstance(raw, dict) or not isinstance(raw.get("places"), list):
                return None
            fetched = datetime.fromisoformat(raw["fetched_at"])
            places = [Place.model_validate(x) for x in raw["places"]]
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > self.max_age:
            return None
        return places

    def put(self, key: str, places: list[Place]) -> None:
        self.backend.write_json(self._key(key), {"fetched_at": datetime.now(timezone.utc).isoformat(),
                                                 "places": [p.model_dump(mode="json") for p in places]})


def default_backend(settings: Settings) -> StorageBackend:
    return LocalStorageBackend(settings.data_root)
