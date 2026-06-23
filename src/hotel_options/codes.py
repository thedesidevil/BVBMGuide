from __future__ import annotations
from src.library.ui.storage import StorageBackend

_KEY = "hotel_options/hotel_codes.json"

_SEEDS: dict[str, str] = {
    "nr": "Non-refundable",
    "br": "Breakfast included",
}


class CodeStore:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def load(self) -> dict[str, str]:
        saved = self._storage.read_json(_KEY) or {}
        return {**_SEEDS, **saved}

    def save(self, codes: dict[str, str]) -> None:
        # Persist only non-seed entries; seeds are re-applied at load time
        to_save = {k: v for k, v in codes.items() if k not in _SEEDS}
        self._storage.write_json(_KEY, to_save)
