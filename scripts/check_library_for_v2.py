"""Readiness check: does the library hold what AIG v2's section writers read?

Usage: python scripts/check_library_for_v2.py --db library_db [--strict]

For every country shard in ``<db>/_country/*.json`` it reports which of the
sections dishes, souvenirs, etiquette, safety, connectivity, getting_around,
health have library content (checkmark) or not (dash), plus the country's
``currency`` in its own column.

How a section is judged (the way AIG v2 does it: ``library.city(c)`` for each
trip city and ``library.country(country)``, fed to ``_library_items``):
- Folders of ``Library.coverage()`` that belong to a country shard: the folder
  name equals the shard name, OR ``Library.country(folder)`` resolves to that
  same shard, OR one name appears in the other as whole words (so
  "Examplia and Neighbours" belongs to shard "Examplia"), all via ``norm_name``.
- The covered cities of those folders are loaded with ``Library.city(c)`` and
  passed with the country dict to ``_library_items(key, cities, [country])``.
  ``_library_items`` is a private name of ``src.aigv2.writing.sections``;
  acceptable for a diagnostic script, and it keeps this check in step with
  what the writers read.
- ``money`` has no library lists in v2 (``_LIB["money"] == []``), so it is shown
  as n/a, never counted as missing, and ignored by ``--strict``. Currency is
  reported separately.

Gaps reported: coverage folders whose ``Library.country(folder)`` is empty and
that belong to no country shard, and per-country missing sections.

Exit code: 1 only if the DB has no country shards or cannot be read; otherwise 0
even with gaps. ``--strict`` also exits 1 when a country has none of the
country-level lists (the lists in ``COUNTRY_LISTS``) nor a currency.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.aigv2.library import Library, LibraryDataError, norm_name  # noqa: E402
from src.aigv2.writing.sections import _library_items  # noqa: E402
from src.library.ingest_core.prompt import COUNTRY_LISTS  # noqa: E402

SECTIONS = ("dishes", "souvenirs", "etiquette", "safety", "connectivity", "getting_around", "health")
TICK, DASH, NA = "✓", "–", "n/a"


def _has_country_content(cdata: dict) -> bool:
    return bool(cdata.get("currency")) or any(cdata.get(n) for n in COUNTRY_LISTS)


def _section_present(key: str, cities: list[dict], cdata: dict) -> bool:
    return bool(_library_items(key, cities, [cdata]))


def _words_in(a: str, b: str) -> bool:
    return bool(a) and re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", b) is not None


def _belongs(folder: str, stem: str, cdata: dict, lib: Library) -> bool:
    f, n = norm_name(folder), norm_name(stem)
    return f == n or _words_in(n, f) or _words_in(f, n) or (bool(cdata) and lib.country(folder) == cdata)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check the library has the content AIG v2 reads.")
    ap.add_argument("--db", required=True, help="library database folder")
    ap.add_argument("--strict", action="store_true",
                    help="also fail when a country has none of the country-level lists")
    args = ap.parse_args(argv)

    root = Path(args.db)
    try:
        lib = Library(root)
        names = sorted(p.stem for p in (root / "_country").glob("*.json")) if (root / "_country").is_dir() else []
        coverage = lib.coverage()
        rows = []
        belonging: set[str] = set()
        for name in names:
            cdata = lib.country(name)
            folders = [f for f in coverage if _belongs(f, name, cdata, lib)]
            belonging.update(folders)
            cities = [lib.city(c) for c in dict.fromkeys(c for f in folders for c in coverage[f])]
            rows.append((name, cdata, {k: _section_present(k, cities, cdata) for k in SECTIONS}))
        gap_folders = [f for f in coverage if f not in belonging and not lib.country(f)]
    except (LibraryDataError, OSError, ValueError) as e:
        print(f"ERROR: cannot read library at {root}: {e!r}")
        return 1

    if not rows:
        print(f"ERROR: no country shards found under {root / '_country'}")
        return 1

    width = max(len(n) for n, _, _ in rows)
    cw = [max(len(k), 3) for k in SECTIONS]
    print("  ".join(["country".ljust(width), *(k.ljust(w) for k, w in zip(SECTIONS, cw)), "money".ljust(5), "currency"]))
    for name, cdata, present in rows:
        cur = cdata.get("currency") or "-"
        cells = [(TICK if present[k] else DASH).ljust(w) for k, w in zip(SECTIONS, cw)]
        print("  ".join([name.ljust(width), *cells, NA.ljust(5), str(cur)]))

    empty = [n for n, c, _ in rows if not _has_country_content(c)]
    missing_total = sum(1 for _, _, p in rows for v in p.values() if not v)
    print()
    for f in gap_folders:
        print(f"GAP: folder '{f}' has no country shard content")
    for n in empty:
        print(f"GAP: country '{n}' has none of the country-level lists")
    no_cur = sum(1 for _, c, _ in rows if not c.get("currency"))
    print(f"{len(rows)} countries, {missing_total} missing sections (money excluded: n/a), {no_cur} without currency, "
          f"{len(gap_folders)} folders without country content, {len(empty)} countries without country-level lists")

    return 1 if (args.strict and empty) else 0


if __name__ == "__main__":
    sys.exit(main())
