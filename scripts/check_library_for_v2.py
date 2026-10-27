"""Readiness check: does the library hold what AIG v2's section writers read?

Usage: python scripts/check_library_for_v2.py --db library_db [--strict]

For every country shard in ``<db>/_country/*.json`` it reports which of the
sections dishes, souvenirs, etiquette, safety, connectivity, getting_around,
health, money have library content (checkmark) or not (dash).

Choices made to keep it simple:
- Content is counted with ``_library_items`` from ``src.aigv2.writing.sections``
  (a private name of another package; acceptable for a diagnostic script) so the
  check agrees with what the writers actually read. It is fed the country shard
  plus the city shards of folders in ``_folder_coverage`` whose folder name equals
  the country name (case-insensitive). Countries without such a folder are judged
  on country-level lists alone.
- ``money`` has no library lists in the writers, so it counts as present when the
  country shard has a ``money`` list or a ``currency``.
- Gaps reported: coverage folders whose ``Library.country(folder)`` is empty, and
  per-country missing sections.

Exit code: 1 only if the DB has no country shards or cannot be read; otherwise 0
even with gaps. ``--strict`` also exits 1 when a country has none of the
country-level lists (the lists in ``COUNTRY_LISTS`` or a currency).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.aigv2.library import Library, LibraryDataError, norm_name  # noqa: E402
from src.aigv2.writing.sections import _library_items  # noqa: E402
from src.library.ingest_core.prompt import COUNTRY_LISTS  # noqa: E402

SECTIONS = ("dishes", "souvenirs", "etiquette", "safety", "connectivity", "getting_around", "health", "money")
TICK, DASH = "✓", "–"


def _has_country_content(cdata: dict) -> bool:
    return bool(cdata.get("currency")) or any(cdata.get(n) for n in COUNTRY_LISTS)


def _section_present(key: str, cities: list[dict], cdata: dict) -> bool:
    if key == "money":
        return bool(cdata.get("money") or cdata.get("currency"))
    return bool(_library_items(key, cities, [cdata]))


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
        for name in names:
            cdata = lib.country(name)
            folders = [f for f in coverage if norm_name(f) == norm_name(name)]
            cities = [lib.city(c) for f in folders for c in coverage[f]]
            rows.append((name, cdata, {k: _section_present(k, cities, cdata) for k in SECTIONS}))
        gap_folders = [f for f in coverage if not lib.country(f)]
    except (LibraryDataError, OSError, ValueError) as e:
        print(f"ERROR: cannot read library at {root}: {e!r}")
        return 1

    if not rows:
        print(f"ERROR: no country shards found under {root / '_country'}")
        return 1

    width = max(len(n) for n, _, _ in rows)
    short = [s[:9] for s in SECTIONS]
    print(f"{'country'.ljust(width)}  " + " ".join(s.ljust(9) for s in short))
    for name, _, present in rows:
        print(f"{name.ljust(width)}  " + " ".join((TICK if present[k] else DASH).ljust(9) for k in SECTIONS))

    empty = [n for n, c, _ in rows if not _has_country_content(c)]
    missing_total = sum(1 for _, _, p in rows for v in p.values() if not v)
    print()
    for f in gap_folders:
        print(f"GAP: folder '{f}' has no country shard content")
    for n in empty:
        print(f"GAP: country '{n}' has none of the country-level lists")
    print(f"{len(rows)} countries, {missing_total} missing sections, {len(gap_folders)} folders without country "
          f"content, {len(empty)} countries without country-level lists")

    return 1 if (args.strict and empty) else 0


if __name__ == "__main__":
    sys.exit(main())
