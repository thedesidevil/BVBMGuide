"""Ordered newer-wins merge of one cleaned extraction into library shards.

Files are merged oldest to newest (Task 4 ordering). For each incoming item
with identity key K, against the existing item with the same K in the same
list of the same shard:

1. K is on the blocklist                          -> ``blocked``
2. no existing item                               -> append, ``added``
3. existing is ``_manual``                        -> keep it; record a conflict
                                                     when content differs, ``protected``
4. existing came from this same file              -> replace in place (no
                                                     ``_replaced_from``), or
                                                     ``unchanged`` if identical
5. incoming rank lower than existing rank         -> ``skipped_older``
6. otherwise                                      -> replace, set
                                                     ``_replaced_from``, ``replaced``

Rank is ``(format rank old=0/new=1, order_date or date.min)``; an existing item
without provenance has the lowest rank. Equal rank: the incoming item wins.

Each shard is read once per call and written once at the end, only if it
changed, so an exception mid-file leaves no half-written shard.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from src.library.ingest_core.countries import canonical_country
from src.library.ingest_core.identity import city_shard_name, item_key, norm_key
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS, TIP_LISTS
from src.library.ui.services.db_service import LibraryDBService

PROVENANCE_KEYS = ("_source_file", "_source_date", "_source_format", "_replaced_from")
_COUNTERS = ("added", "replaced", "unchanged", "skipped_older", "protected", "blocked")
_FMT_RANK = {"old": 0, "new": 1}
_LOWEST = (-1, date.min)


@dataclass
class FileMeta:
    source_file: str
    order_date: date | None
    fmt: Literal["new", "old"]
    folder: str


@dataclass
class MergeStats:
    added: int = 0
    replaced: int = 0
    unchanged: int = 0
    skipped_older: int = 0
    protected: int = 0
    blocked: int = 0
    by_city: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, shard: str, counter: str) -> None:
        setattr(self, counter, getattr(self, counter) + 1)
        per = self.by_city.setdefault(shard, {c: 0 for c in _COUNTERS})
        per[counter] += 1

    def __iadd__(self, other: "MergeStats") -> "MergeStats":
        for c in _COUNTERS:
            setattr(self, c, getattr(self, c) + getattr(other, c))
        for shard, counts in other.by_city.items():
            per = self.by_city.setdefault(shard, {c: 0 for c in _COUNTERS})
            for c in _COUNTERS:
                per[c] += counts.get(c, 0)
        return self


def resolve_city_shard(db: LibraryDBService, raw: str) -> str:
    """Existing shard with the same ``norm_key`` wins; else ``city_shard_name``."""
    target = norm_key(raw)
    for name in db.list_city_shards():
        if norm_key(name) == target:
            return name
    return city_shard_name(raw)


def _content(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in PROVENANCE_KEYS}


def _rank_of(fmt, order_date) -> tuple:
    if isinstance(order_date, str):
        try:
            order_date = date.fromisoformat(order_date)
        except ValueError:
            order_date = None
    return (_FMT_RANK.get(fmt, 0), order_date or date.min)


def _existing_rank(item: dict) -> tuple:
    if not item.get("_source_file"):
        return _LOWEST
    return _rank_of(item.get("_source_format"), item.get("_source_date"))


class _Shard:
    """One shard loaded into memory for the duration of a merge call."""

    def __init__(self, key: str, data: dict | None, lists: tuple[str, ...], is_city: bool):
        self.key = key
        self.is_new = data is None
        if data is None:
            data = {name: [] for name in lists}
            if is_city:
                data["source_files"] = []
        self.data = data
        self.changed = False
        self.seen: set[tuple[str, str]] = set()  # (list, key) merged in this call
        self._indexes: dict[str, dict[str, int]] = {}

    def index(self, list_name: str) -> dict[str, int]:
        idx = self._indexes.get(list_name)
        if idx is None:
            idx = {}
            for i, it in enumerate(self.list(list_name)):
                if isinstance(it, dict):
                    k = item_key(list_name, it)
                    if k and k not in idx:
                        idx[k] = i
            self._indexes[list_name] = idx
        return idx

    def list(self, list_name: str) -> list:
        lst = self.data.get(list_name)
        if not isinstance(lst, list):
            lst = self.data[list_name] = []
        return lst


class _Merger:
    def __init__(self, db: LibraryDBService, meta: FileMeta):
        self.db = db
        self.meta = meta
        self.stats = MergeStats()
        self.rank = _rank_of(meta.fmt, meta.order_date)
        self.provenance = {
            "_source_file": meta.source_file,
            "_source_date": meta.order_date.isoformat() if meta.order_date else None,
            "_source_format": meta.fmt,
        }
        self.blocked = {
            (_block_scope(e.get("city", "")), e.get("list"), e.get("key"))
            for e in db.get_blocklist()
            if isinstance(e, dict)
        }
        self.cities: dict[str, _Shard] = {}
        self.countries: dict[str, _Shard] = {}
        self._known_shards = None
        self._known_countries = None

    # --- shard loading -------------------------------------------------

    def city(self, raw: str) -> _Shard:
        target = norm_key(raw)
        for name, shard in self.cities.items():
            if norm_key(name) == target:
                return shard
        if self._known_shards is None:
            self._known_shards = self.db.list_city_shards()
        name = next((n for n in self._known_shards if norm_key(n) == target), None)
        name = name or city_shard_name(raw)
        shard = _Shard(name, self.db.get_city_data(name), CITY_LISTS, True)
        self.cities[name] = shard
        return shard

    def existing_city(self, raw: str) -> _Shard | None:
        """Shard for ``raw`` only if it exists in the DB or holds items written in
        this call; never creates a new shard."""
        target = norm_key(raw)
        for shard in self.cities.values():
            if norm_key(shard.key) == target:
                return shard if (not shard.is_new or shard.changed) else None
        name = resolve_city_shard(self.db, raw)
        if self.db.get_city_data(name) is None:
            return None
        return self.city(name)

    def country(self, raw: str) -> _Shard:
        raw = canonical_country(raw)
        target = norm_key(raw)
        for name, shard in self.countries.items():
            if norm_key(name) == target:
                return shard
        if self._known_countries is None:
            self._known_countries = [
                k[len("_country/"):-len(".json")]
                for k in self.db.backend.list_keys("_country/")
                if k.endswith(".json") and "/" not in k[len("_country/"):]
            ]
        name = next((n for n in self._known_countries if norm_key(n) == target), None)
        name = name or raw.strip()
        shard = _Shard(f"_country/{name}", self.db.get_country_data(name), COUNTRY_LISTS, False)
        self.countries[name] = shard
        return shard

    # --- item rules ----------------------------------------------------

    def merge_item(self, shard: _Shard, block_city: str, list_name: str, item: dict) -> None:
        key = item_key(list_name, item)
        if not key or (list_name, key) in shard.seen:
            # no identity, or a repeat within this file: first occurrence wins
            return
        shard.seen.add((list_name, key))
        if (_block_scope(block_city), list_name, key) in self.blocked:
            self.stats.bump(shard.key, "blocked")
            return
        incoming = {**_content(item), **self.provenance}
        lst = shard.list(list_name)
        idx = shard.index(list_name)
        pos = idx.get(key)
        if pos is None:  # rule 2
            idx[key] = len(lst)
            lst.append(incoming)
            self._touch(shard)
            self.stats.bump(shard.key, "added")
            return
        existing = lst[pos]
        if existing.get("_manual"):  # rule 3
            if _content(existing) != {**_content(item), **_manual_fields(existing)}:
                self._conflict(shard, list_name, key, _content(item))
            self.stats.bump(shard.key, "protected")
            return
        if existing.get("_source_file") == self.meta.source_file:  # rule 4
            if _content(existing) == _content(item):
                # same content; refresh provenance if the order date/format changed
                for k in ("_source_date", "_source_format"):
                    if existing.get(k) != self.provenance[k]:
                        existing[k] = self.provenance[k]
                        shard.changed = True
                self.stats.bump(shard.key, "unchanged")
                return
            if "_replaced_from" in existing:
                incoming["_replaced_from"] = existing["_replaced_from"]
            lst[pos] = incoming
            self._touch(shard)
            self.stats.bump(shard.key, "replaced")
            return
        if self.rank < _existing_rank(existing):  # rule 5
            self.stats.bump(shard.key, "skipped_older")
            return
        incoming["_replaced_from"] = existing.get("_source_file")  # rule 6
        lst[pos] = incoming
        self._touch(shard)
        self.stats.bump(shard.key, "replaced")

    def _conflict(self, shard: _Shard, list_name: str, key: str, incoming: dict) -> None:
        conflicts = shard.data.get("_conflicts")
        if not isinstance(conflicts, list):
            conflicts = []
        entry = {"list": list_name, "key": key, "incoming": incoming,
                 "source_file": self.meta.source_file}
        if entry not in conflicts:
            shard.data["_conflicts"] = conflicts + [entry]
            shard.changed = True

    def _touch(self, shard: _Shard) -> None:
        shard.changed = True
        sources = shard.data.get("source_files")
        if isinstance(sources, list) and self.meta.source_file not in sources:
            sources.append(self.meta.source_file)

    def set_currency(self, shard: _Shard, currency: str) -> None:
        """Last-write-wins by rank; ``_currency_source`` keeps the winner's provenance."""
        source = shard.data.get("_currency_source")
        if source == self.provenance and shard.data.get("currency") == currency:
            return
        if shard.data.get("currency") and isinstance(source, dict):
            if self.rank < _rank_of(source.get("_source_format"), source.get("_source_date")):
                return
        shard.data["currency"] = currency
        shard.data["_currency_source"] = dict(self.provenance)
        shard.changed = True

    # --- write ---------------------------------------------------------

    def flush(self) -> None:
        for name, shard in self.countries.items():
            if shard.changed:
                self.db.save_country_data(name, shard.data)
        changed_cities = [n for n, s in self.cities.items() if s.changed]
        for name in changed_cities:
            self.db.save_city_data(name, self.cities[name].data)
        for name in changed_cities:
            self.db.set_review_status(name, "pending")


def _block_scope(scope) -> str:
    """Normalised blocklist scope; ``_country/<X>`` goes through ``canonical_country``."""
    scope = str(scope or "")
    if scope.startswith("_country/"):
        return "_country/" + norm_key(canonical_country(scope[len("_country/"):]))
    return norm_key(scope)


def _manual_fields(item: dict) -> dict:
    return {k: v for k, v in item.items() if k.startswith("_manual")}


def merge_extraction(db: LibraryDBService, data: dict, meta: FileMeta) -> MergeStats:
    """Merge one cleaned extraction into city and country shards.

    Blocklist entries are ``{"city": <shard>, "list": <list name>, "key": <item_key>}``.
    For a city item ``<shard>`` is the city shard name; for a country-level item it
    is ``"_country/<Country>"`` (the same key used in ``MergeStats.by_city``). Shard
    names are compared through ``norm_key``, so case/accent variants match.

    City-level ``currency`` is set only on city shards that already exist or that
    receive items in this call; ``city_countries`` never creates a shard.
    """
    m = _Merger(db, meta)

    for list_name in CITY_LISTS:
        items = data.get(list_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            targets: list[str] = []
            if list_name in TIP_LISTS and isinstance(item.get("cities"), list):
                targets = [c for c in item["cities"] if isinstance(c, str) and c.strip()]
            if not targets and isinstance(item.get("city"), str) and item["city"].strip():
                targets = [item["city"]]
            # no usable city: skipped, nothing counted, nothing written
            seen: set[str] = set()
            for raw in targets:
                shard = m.city(raw)
                if shard.key in seen:
                    continue
                seen.add(shard.key)
                m.merge_item(shard, shard.key, list_name, item)

    city_countries = data.get("city_countries") or {}
    for entry in data.get("country_content") or []:
        if not isinstance(entry, dict):
            continue
        country = entry.get("country")
        if not isinstance(country, str) or not country.strip():
            continue
        shard = m.country(country)
        for list_name in COUNTRY_LISTS:
            items = entry.get(list_name)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    m.merge_item(shard, shard.key, list_name, item)
        currency = entry.get("currency")
        if isinstance(currency, str) and currency.strip():
            currency = currency.strip()
            m.set_currency(shard, currency)
            if isinstance(city_countries, dict):
                for city, c in city_countries.items():
                    if (isinstance(city, str) and city.strip() and isinstance(c, str)
                            and norm_key(canonical_country(c)) == norm_key(canonical_country(country))):
                        city_shard = m.existing_city(city)
                        if city_shard is not None:
                            m.set_currency(city_shard, currency)

    m.flush()
    return m.stats


def country_coverage(data: dict) -> dict[str, list[str]]:
    """Cleaned extraction -> ``{canonical country: [covered cities]}``, multi-country guides only.

    Cities without a country mapping are skipped. A guide spanning one country (or none)
    returns ``{}`` so domestic trips do not create extra coverage entries.
    """
    covered = data.get("covered_cities")
    cc = data.get("city_countries")
    if not isinstance(covered, list) or not isinstance(cc, dict):
        return {}
    by_norm = {norm_key(k): v for k, v in cc.items() if isinstance(k, str)}
    out: dict[str, list[str]] = {}
    for city in covered:
        if not isinstance(city, str) or not city.strip():
            continue
        raw = by_norm.get(norm_key(city))
        if not isinstance(raw, str) or not raw.strip():
            continue
        cities = out.setdefault(canonical_country(raw), [])
        if norm_key(city) not in {norm_key(c) for c in cities}:
            cities.append(city)
    return out if len(out) > 1 else {}
