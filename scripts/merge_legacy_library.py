"""One-off: copy every entry of the OLD library into the rebuilt (NEW) library.

Usage:
    python3 scripts/merge_legacy_library.py --old PATH --new PATH [--apply] [--report PATH]

Dry-run by default: reads both libraries and writes only the markdown report.
With --apply the NEW library gets every old item that is not a duplicate,
marked with ``_legacy`` / ``_needs_verification`` so it can be verified later.
Existing new items are never modified; ``_manual`` is never set; the old
library is never written. Re-running --apply adds nothing (dedup by item key).
"""

import argparse
import copy
import difflib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.library.ingest_core.countries import canonical_country  # noqa: E402
from src.library.ingest_core.identity import city_shard_name, item_key, norm_key  # noqa: E402
from src.library.ingest_core.merge import _block_scope  # noqa: E402
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS  # noqa: E402
from src.library.ui.services.db_service import LibraryDBService  # noqa: E402
from src.library.ui.storage import LocalStorageBackend  # noqa: E402

LEGACY_FROM = "library_db backup 2026-10-28"
DEFAULT_REPORT = "/tmp/legacy_merge_report.md"

# Regional / combined folder names that belong to exactly one country.
REGIONAL_TABLE = {
    "Almaty Kazakhstan": "Kazakhstan",
    "Andamans": "India",
    "Goa": "India",
    "Rajasthan": "India",
    "North India": "India",
    "Northeast India": "India",
    "Karnataka, Kerala and Tamil Nadu": "India",
    "Bali Indonesia": "Indonesia",
    "England and Scotland": "UK",
    "Dubai and Abu Dhabi - UAE": "United Arab Emirates",
}

# Genuinely multi-country folder names: items are routed by city.
MULTI_COUNTRY = ("Greece and Turkey", "Singapore and Malaysia", "South America")

_CITY_COUNTRY_RAW = {
    "Singapore": ["Singapore"],
    "Malaysia": ["Kuala Lumpur", "Langkawi", "Penang", "Malacca", "Melaka", "Kota Kinabalu", "Genting"],
    "Greece": ["Athens", "Santorini", "Mykonos", "Crete", "Rhodes", "Naxos", "Meteora", "Delphi"],
    "Türkiye": ["Istanbul", "Cappadocia", "Goreme", "Ankara", "Antalya", "Pamukkale", "Izmir", "Bodrum"],
    "Peru": ["Lima", "Cusco", "Machu Picchu", "Aguas Calientes", "Ollantaytambo", "Urubamba", "Pisaq",
             "Sacred Valley", "Arequipa", "Puno"],
}
CITY_COUNTRY = {norm_key(c): country for country, cs in _CITY_COUNTRY_RAW.items() for c in cs}
_REGIONAL = {norm_key(k): v for k, v in REGIONAL_TABLE.items()}
_MULTI = {norm_key(k) for k in MULTI_COUNTRY}

ROUTES = ("city_existing", "city_new_shard", "country_merge", "country_routed", "country_unrouted")
COUNTERS = ("scanned", "duplicate", "blocklisted", "no_identity", "added")
NAME_FIELDS = ("name", "item", "tip", "text", "english", "service", "mode", "provider", "type", "from")
TEXT_FIELDS = ("tip", "text")


def is_live_library(path: Path) -> bool:
    """Same logic as ``src.library.__main__._is_live_library``."""
    resolved = path.resolve()
    repo_db = (Path(__file__).resolve().parents[1] / "library_db").resolve()
    for live in {Path("library_db").resolve(), repo_db}:
        if resolved == live or resolved.is_relative_to(live):
            return True
    return False


def _list_country_shards(db: LibraryDBService) -> list[str]:
    out = []
    for k in db.backend.list_keys("_country/"):
        rest = k[len("_country/"):]
        if k.endswith(".json") and "/" not in rest:
            out.append(rest[:-5])
    return sorted(out)


def _iso_date(mtime) -> str | None:
    try:
        return datetime.fromtimestamp(float(mtime), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _label(item: dict) -> str:
    for f in NAME_FIELDS:
        if item.get(f):
            return str(item[f])[:90]
    return "?"


def _text_norm(item: dict) -> str:
    for f in TEXT_FIELDS:
        if item.get(f):
            return norm_key(item[f])
    return ""


class Shard:
    def __init__(self, kind: str, name: str, data: dict | None, lists: tuple[str, ...]):
        self.kind, self.name = kind, name  # kind: "city" | "country"
        self.is_new = data is None
        if data is None:
            data = {n: [] for n in lists}
            if kind == "city":
                data["source_files"] = []
        self.data = data
        self.changed = False
        self.added = 0
        self._keys: dict[str, set[str]] = {}

    @property
    def display(self) -> str:
        return f"_country/{self.name}" if self.kind == "country" else self.name

    def list(self, list_name: str) -> list:
        lst = self.data.get(list_name)
        if not isinstance(lst, list):
            lst = self.data[list_name] = []
        return lst

    def keys(self, list_name: str) -> set[str]:
        ks = self._keys.get(list_name)
        if ks is None:
            ks = {item_key(list_name, it) for it in self.list(list_name) if isinstance(it, dict)}
            ks.discard("")
            self._keys[list_name] = ks
        return ks


class Merger:
    def __init__(self, old: LibraryDBService, new: LibraryDBService):
        self.old, self.new = old, new
        self.blocked = {
            (_block_scope(e.get("city", "")), e.get("list"), e.get("key"))
            for e in new.get_blocklist() if isinstance(e, dict)
        }
        self.new_cities = new.list_city_shards()
        self.new_countries = _list_country_shards(new)
        self.cities: dict[str, Shard] = {}      # norm_key -> Shard
        self.countries: dict[str, Shard] = {}   # norm_key -> Shard
        self.counts: dict[str, Counter] = defaultdict(Counter)   # by list
        self.route_scanned: Counter = Counter()
        self.route_added: Counter = Counter()
        self.legacy_notes = 0
        self.near_dups = 0
        self.manual_stripped = 0
        self.samples: list[tuple[str, str, str]] = []
        self._cross: dict[str, dict[str, str]] | None = None

    # --- shards ---------------------------------------------------------
    def city_shard(self, raw: str) -> Shard:
        t = norm_key(raw)
        if t in self.cities:
            return self.cities[t]
        name = next((n for n in self.new_cities if norm_key(n) == t), None)
        data = self.new.get_city_data(name) if name else None
        sh = Shard("city", name or city_shard_name(raw), data, CITY_LISTS)
        self.cities[t] = sh
        return sh

    def country_shard(self, exact_name: str, resolve: bool) -> Shard:
        if resolve:
            exact_name = canonical_country(exact_name)
            t = norm_key(exact_name)
            name = next((n for n in self.new_countries if norm_key(n) == t), None) or exact_name.strip()
        else:
            name = exact_name
            t = norm_key(name)
        t = norm_key(name)
        if t in self.countries:
            return self.countries[t]
        data = self.new.get_country_data(name)
        sh = Shard("country", name, data, COUNTRY_LISTS)
        self.countries[t] = sh
        return sh

    def cross_index(self) -> dict[str, dict[str, str]]:
        if self._cross is None:
            idx: dict[str, dict[str, str]] = defaultdict(dict)
            for n in self.new_cities:
                d = self.new.get_city_data(n) or {}
                for ln, lst in d.items():
                    if isinstance(lst, list) and ln != "source_files":
                        for it in lst:
                            if isinstance(it, dict):
                                k = item_key(ln, it)
                                if k:
                                    idx[ln].setdefault(k, n)
            self._cross = idx
        return self._cross

    # --- item handling ----------------------------------------------------
    def add_items(self, shard: Shard, route: str, old_shard_label: str, list_name: str, items: list,
                  block_scope: str) -> None:
        lst_counts = self.counts[list_name]
        for item in items:
            lst_counts["scanned"] += 1
            self.route_scanned[route] += 1
            key = item_key(list_name, item) if isinstance(item, dict) else ""
            if not key:
                lst_counts["no_identity"] += 1
                continue
            if key in shard.keys(list_name):
                lst_counts["duplicate"] += 1
                continue
            if (_block_scope(block_scope), list_name, key) in self.blocked:
                lst_counts["blocklisted"] += 1
                continue
            new_item = copy.deepcopy(item)
            for k in [k for k in new_item if k.startswith("_manual")]:
                del new_item[k]
                self.manual_stripped += 1
            new_item.update({
                "_legacy": True,
                "_needs_verification": True,
                "_legacy_from": LEGACY_FROM,
                "_legacy_shard": old_shard_label,
                "_source_format": "old",
                "_source_date": _iso_date(item.get("_source_mtime")),
            })
            if shard.kind == "city" and shard.is_new:
                other = self.cross_index().get(list_name, {}).get(key)
                if other and other != shard.name:
                    new_item["_legacy_note"] = f"same name also exists in {other}"
                    self.legacy_notes += 1
            txt = _text_norm(new_item)
            if txt:
                for ex in shard.list(list_name):
                    if isinstance(ex, dict):
                        et = _text_norm(ex)
                        if et and _similar(txt, et):
                            self.near_dups += 1
                            break
            shard.list(list_name).append(new_item)
            shard.keys(list_name).add(key)
            shard.changed = True
            shard.added += 1
            lst_counts["added"] += 1
            self.route_added[route] += 1
            self.samples.append((list_name, shard.display, _label(new_item)))

    def run(self) -> None:
        for name in sorted(self.old.list_city_shards()):
            data = self.old.get_city_data(name) or {}
            shard = self.city_shard(name)
            route = "city_new_shard" if shard.is_new else "city_existing"
            for ln, items in data.items():
                if isinstance(items, list) and ln != "source_files" and not ln.startswith("_"):
                    self.add_items(shard, route, name, ln, items, shard.name)
        for name in _list_country_shards(self.old):
            data = self.old.get_country_data(name) or {}
            label = f"_country/{name}"
            nk = norm_key(name)
            for ln, items in data.items():
                if not isinstance(items, list) or ln.startswith("_"):
                    continue
                if nk in _MULTI:
                    self._route_multi(name, label, ln, items)
                elif nk in _REGIONAL:
                    sh = self.country_shard(_REGIONAL[nk], True)
                    self.add_items(sh, "country_merge", label, ln, items, f"_country/{sh.name}")
                else:
                    sh = self.country_shard(name, True)
                    self.add_items(sh, "country_merge", label, ln, items, f"_country/{sh.name}")

    def _route_multi(self, name: str, label: str, ln: str, items: list) -> None:
        routed: dict[str, list] = defaultdict(list)
        unrouted: list = []
        for it in items:
            country = None
            if isinstance(it, dict):
                cities = list(it.get("cities") or []) + [it.get("city")]
                for c in cities:
                    if c and norm_key(c) in CITY_COUNTRY:
                        country = CITY_COUNTRY[norm_key(c)]
                        break
            (routed[country] if country else unrouted).append(it)
        for country, its in routed.items():
            sh = self.country_shard(country, True)
            self.add_items(sh, "country_routed", label, ln, its, f"_country/{sh.name}")
        if unrouted:
            sh = self.country_shard(name, False)
            self.add_items(sh, "country_unrouted", label, ln, unrouted, f"_country/{sh.name}")

    # --- output -------------------------------------------------------------
    def changed_shards(self) -> list[Shard]:
        return [s for s in [*self.cities.values(), *self.countries.values()] if s.changed]

    def write(self) -> None:
        for s in self.changed_shards():
            if s.kind == "city":
                self.new.save_city_data(s.name, s.data)
            else:
                self.new.save_country_data(s.name, s.data)


def _similar(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 0.2 * max(len(a), len(b)):
        return False
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= 0.9 and m.quick_ratio() >= 0.9 and m.ratio() >= 0.9


def merge_coverage(old: LibraryDBService, new: LibraryDBService, apply: bool) -> int:
    """Union old ``_folder_coverage`` into the new index; returns cities newly added."""
    before = {k: list(v) for k, v in new.get_folder_coverage().items()}
    for folder, cities in old.get_folder_coverage().items():
        new.add_folder_coverage(folder, list(cities))
    after = new.get_folder_coverage()
    added = sum(len(v) - len(before.get(k, [])) for k, v in after.items())
    if apply and added:
        new.save_index()
    return added


def build_report(m: Merger, apply: bool, cov_added: int) -> str:
    tot = Counter()
    for c in m.counts.values():
        tot.update(c)
    L = [f"# Legacy library merge report ({'APPLIED' if apply else 'DRY RUN - nothing written'})", ""]
    L += ["## Counts per list", "",
          "| list | old scanned | duplicates skipped | blocklisted | no identity | added |", "|---|---|---|---|---|---|"]
    for ln in sorted(m.counts):
        c = m.counts[ln]
        L.append(f"| {ln} | " + " | ".join(str(c[k]) for k in COUNTERS) + " |")
    L.append("| **total** | " + " | ".join(f"**{tot[k]}**" for k in COUNTERS) + " |")
    L += ["", "## Counts by route", "", "| route | old scanned | added |", "|---|---|---|"]
    desc = {"city_existing": "merged into existing city shard", "city_new_shard": "new shard from old-only city",
            "country_merge": "country merge", "country_routed": "country routed by city table",
            "country_unrouted": "country unrouted -> legacy shard"}
    for r in ROUTES:
        L.append(f"| {desc[r]} | {m.route_scanned[r]} | {m.route_added[r]} |")
    created = sorted((s for s in m.changed_shards() if s.is_new), key=lambda s: (-s.added, s.display))
    created_all = [s for s in [*m.cities.values(), *m.countries.values()] if s.is_new and s.changed]
    L += ["", f"## Shards created: {len(created_all)} "
              f"({sum(1 for s in created_all if s.kind == 'city')} city, "
              f"{sum(1 for s in created_all if s.kind == 'country')} country)", "", "Top 30 by item count:", ""]
    for s in created[:30]:
        L.append(f"- {s.display}: {s.added}")
    changed = m.changed_shards()
    L += ["", f"## Shards changed in total: {len(changed)}",
          f"## Items with `_legacy_note` (same name in another new city shard): {m.legacy_notes}",
          f"## Near-duplicate tip items (difflib >= 0.9, INFO ONLY, still added): {m.near_dups}",
          f"## Old `_manual*` fields stripped from copies: {m.manual_stripped}",
          f"## Index `_folder_coverage` cities added: {cov_added}", "", "## 15 sample added items", ""]
    n = len(m.samples)
    step = max(1, n // 15)
    for ln, shard, label in m.samples[::step][:15]:
        L.append(f"- [{ln}] {shard}: {label}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument("--apply", action="store_true", help="write into --new (default: dry run)")
    ap.add_argument("--report", type=Path, default=Path(DEFAULT_REPORT))
    args = ap.parse_args(argv)

    def fail(msg: str) -> int:
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    if is_live_library(args.new):
        return fail("refusing to write into the live library_db; use a rebuilt folder (e.g. library_db_new)")
    if args.old.resolve() == args.new.resolve():
        return fail("--old and --new are the same path")
    if not (args.old / "_index.json").exists() and not args.old.is_dir():
        return fail(f"--old {args.old} is not a library folder")
    if not (args.new / "_index.json").exists():
        return fail(f"--new {args.new} has no _index.json")

    old = LibraryDBService(LocalStorageBackend(args.old))
    new = LibraryDBService(LocalStorageBackend(args.new))
    m = Merger(old, new)
    m.run()
    cov_added = merge_coverage(old, new, apply=False)
    if args.apply:
        m.write()
        if cov_added:
            new.save_index()
    report = build_report(m, args.apply, cov_added)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    tot = Counter()
    for c in m.counts.values():
        tot.update(c)
    print(f"{'APPLIED' if args.apply else 'DRY RUN'}: scanned={tot['scanned']} duplicates={tot['duplicate']} "
          f"blocklisted={tot['blocklisted']} no_identity={tot['no_identity']} added={tot['added']}; report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
