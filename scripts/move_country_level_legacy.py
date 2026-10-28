"""One-off: move country-level legacy entries out of country-named city shards into the country shards.

Dry-run by default; pass --apply to write. Only touches library_db_new.
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from src.library.ingest_core.countries import canonical_country
from src.library.ingest_core.identity import item_key
from src.library.ui.services.db_service import LibraryDBService
from src.library.ui.storage import LocalStorageBackend

APPLY = "--apply" in sys.argv
NEW = Path("library_db_new")
SCOPE = ["phrases", "safety_tips", "emergency_contacts", "connectivity_tips", "health_tips", "transport_options"]
ALL = ["restaurants", "attractions", "hotels", "local_dishes", "souvenirs", "phrases", "safety_tips",
       "emergency_contacts", "connectivity_tips", "transport_options", "health_tips", "route_guides", "season_notes"]


def nk(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


db = LibraryDBService(LocalStorageBackend(NEW))
names = json.load(open("/tmp/legacy_only_shards.json"))
stems = {nk(p.stem): p.stem for p in (NEW / "_country").glob("*.json")}
cshards, ckeys = {}, {}
rows, gained = [], Counter()
before_total = after_remaining = moved_total = dup_total = noid_total = 0
deleted = []

for k in sorted(names):
    cc = canonical_country(k)
    if nk(cc) not in stems:
        continue
    stem = stems[nk(cc)]
    shard = db.get_city_data(k)
    if shard is None:
        continue
    if stem not in cshards:
        cshards[stem] = db.get_country_data(stem)
        ckeys[stem] = {l: {item_key(l, i) for i in cshards[stem].get(l) or [] if isinstance(i, dict)} for l in SCOPE}
    csh = cshards[stem]
    moved = dup = noid = 0
    for l in SCOPE:
        keep = []
        for it in shard.get(l) or []:
            before_total += 1
            if not isinstance(it, dict):
                keep.append(it)
                continue
            key = item_key(l, it)
            if not key:
                keep.append(it)
                noid += 1
            elif key in ckeys[stem][l]:
                dup += 1
            else:
                csh.setdefault(l, []).append(it)
                ckeys[stem][l].add(key)
                moved += 1
                gained[(stem, l)] += 1
        shard[l] = keep
    remaining = sum(len([i for i in (shard.get(l) or []) if isinstance(i, dict)]) for l in ALL)
    city_scope = sum(len(shard.get(l) or []) for l in ["local_dishes", "souvenirs", "restaurants", "attractions", "hotels"])
    before_total += city_scope
    after_remaining += remaining
    moved_total += moved
    dup_total += dup
    noid_total += noid
    rows.append((k, stem, moved, dup, noid, remaining))
    if APPLY:
        if remaining == 0:
            db.backend.delete(f"{k}.json")
            deleted.append(k)
        else:
            db.save_city_data(k, shard)

if APPLY:
    for stem, csh in cshards.items():
        db.save_country_data(stem, csh)

print(("APPLIED" if APPLY else "DRY RUN"), "-", len(rows), "country-named shards")
print(f"{'shard':<18}{'-> country shard':<22}{'moved':>6}{'dup':>5}{'no-id':>6}{'stay':>6}")
for k, stem, m, d, n, r in sorted(rows, key=lambda x: -x[2]):
    print(f"{k:<18}{stem:<22}{m:>6}{d:>5}{n:>6}{r:>6}")
print(f"\nentries examined {before_total} | moved to country shards {moved_total} | exact duplicates dropped {dup_total} | no identity kept {noid_total} | city-level entries left in place {after_remaining - noid_total}")
print("empty shards", "deleted:" if APPLY else "that would be deleted:", [k for k, _, _, _, _, r in rows if r == 0])
by_country = defaultdict(Counter)
for (stem, l), n in gained.items():
    by_country[stem][l] = n
print("\ngained by country shard:", {s: sum(c.values()) for s, c in sorted(by_country.items(), key=lambda x: -sum(x[1].values()))})
