"""Quality checks for the AI-extracted library database."""

import json
import random
import re
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Optional

import fitz
from docx import Document
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .builder import LibraryDatabase

console = Console()


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class QCIssue(BaseModel):
    severity: Severity
    category: str
    destination: str
    entity_type: str
    entity_name: str
    message: str
    source_file: Optional[str] = None


class QCReport(BaseModel):
    destinations_checked: int
    total_restaurants: int
    total_attractions: int
    issues: list[QCIssue]
    health_score: float


# Patterns that indicate field contamination (distances, directions, hotel proximity)
_CONTAMINATION_PATTERNS = re.compile(
    r"\b(\d+\s*min|minutes?\s*(walk|drive|by|from|away)|"
    r"walk\s*from|drive\s*from|metro|cab|taxi\s*from|"
    r"near\s*(the|your|our|\w+)?\s*(hotel|airbnb|hostel|resort|stay)\b|"
    r"from\s*(the|your|our)?\s*(hotel|airbnb|hostel|resort|stay)|"
    r"close\s*to\s*(the|your)|"
    r"walking\s*distance|short\s*(walk|drive|ride))\b",
    re.IGNORECASE,
)

# Generic restaurant names that suggest hallucination
_GENERIC_NAME_PATTERNS = re.compile(
    r"^(local\s+restaurant|traditional\s+cafe|street\s+food\s+(place|stall)|"
    r"local\s+eatery|nearby\s+restaurant|the\s+restaurant|small\s+cafe|"
    r"a\s+(small|local|nearby)\s+\w+)$",
    re.IGNORECASE,
)


class LibraryQC:
    def __init__(self, db_path: Path, library_path: Path):
        self.db_path = db_path
        self.library_path = library_path
        self.db = LibraryDatabase(db_path)
        self.db.load()

    def run(
        self,
        verify_sources: bool = False,
        sample_size: int = 3,
        max_destinations: int = 20,
    ) -> QCReport:
        data = self.db.data
        destinations = data.get("destinations", {})

        issues: list[QCIssue] = []
        total_restaurants = 0
        total_attractions = 0

        for dest, dest_data in destinations.items():
            total_restaurants += len(dest_data.get("restaurants", []))
            total_attractions += len(dest_data.get("attractions", []))

        issues.extend(self._check_required_fields(destinations))
        issues.extend(self._check_file_accounting(data))
        issues.extend(self._check_duplicates(destinations))
        issues.extend(self._check_city_attribution(data))
        issues.extend(self._check_statistical_outliers(destinations))
        issues.extend(self._check_contamination(destinations))

        if verify_sources:
            issues.extend(
                self._verify_sources(destinations, sample_size, max_destinations)
            )

        score = self._compute_score(issues)

        return QCReport(
            destinations_checked=len(destinations),
            total_restaurants=total_restaurants,
            total_attractions=total_attractions,
            issues=issues,
            health_score=score,
        )

    def spot_check(self, sample_count: int = 50) -> dict[str, list[str]]:
        """Collect random unique values per attribute for manual review."""
        data = self.db.data
        destinations = data.get("destinations", {})

        fields_to_sample = [
            "name",
            "cuisine_type",
            "hours",
            "area",
            "nearby_landmarks",
            "highlights",
            "must_try_dishes",
            "best_for",
            "price_range",
            "ambience",
        ]

        buckets: dict[str, set[str]] = {f: set() for f in fields_to_sample}

        all_restaurants = []
        for dest_data in destinations.values():
            all_restaurants.extend(dest_data.get("restaurants", []))

        for r in all_restaurants:
            for field in fields_to_sample:
                val = r.get(field)
                if val is None:
                    continue
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str) and item.strip():
                            buckets[field].add(item.strip())
                elif isinstance(val, str) and val.strip():
                    buckets[field].add(val.strip())

        result: dict[str, list[str]] = {}
        for field, values in buckets.items():
            vals = list(values)
            if len(vals) > sample_count:
                vals = random.sample(vals, sample_count)
            else:
                random.shuffle(vals)
            result[field] = vals

        return result

    def _check_required_fields(self, destinations: dict) -> list[QCIssue]:
        issues = []
        for dest, data in destinations.items():
            for r in data.get("restaurants", []):
                if not r.get("name", "").strip():
                    issues.append(QCIssue(
                        severity=Severity.CRITICAL,
                        category="missing_field",
                        destination=dest,
                        entity_type="restaurant",
                        entity_name="(empty name)",
                        message="Restaurant has no name",
                    ))
                elif not r.get("city", "").strip():
                    issues.append(QCIssue(
                        severity=Severity.CRITICAL,
                        category="missing_field",
                        destination=dest,
                        entity_type="restaurant",
                        entity_name=r["name"],
                        message="Missing city field",
                    ))
                elif not r.get("cuisine_type"):
                    issues.append(QCIssue(
                        severity=Severity.WARNING,
                        category="missing_field",
                        destination=dest,
                        entity_type="restaurant",
                        entity_name=r["name"],
                        message="Missing cuisine_type",
                    ))

                if _GENERIC_NAME_PATTERNS.match(r.get("name", "")):
                    issues.append(QCIssue(
                        severity=Severity.WARNING,
                        category="generic_name",
                        destination=dest,
                        entity_type="restaurant",
                        entity_name=r["name"],
                        message="Suspiciously generic restaurant name — possible hallucination",
                    ))

            for a in data.get("attractions", []):
                if not a.get("name", "").strip():
                    issues.append(QCIssue(
                        severity=Severity.CRITICAL,
                        category="missing_field",
                        destination=dest,
                        entity_type="attraction",
                        entity_name="(empty name)",
                        message="Attraction has no name",
                    ))
                elif not a.get("city", "").strip():
                    issues.append(QCIssue(
                        severity=Severity.WARNING,
                        category="missing_field",
                        destination=dest,
                        entity_type="attraction",
                        entity_name=a["name"],
                        message="Missing city field",
                    ))
        return issues

    def _check_file_accounting(self, data: dict) -> list[QCIssue]:
        issues = []
        processed = data.get("_processed_files", {})

        for rel_path in processed:
            full_path = self.library_path / rel_path
            if not full_path.exists():
                issues.append(QCIssue(
                    severity=Severity.CRITICAL,
                    category="orphan_reference",
                    destination="(global)",
                    entity_type="file",
                    entity_name=rel_path,
                    message="Referenced in _processed_files but not on disk",
                ))

        actual_files = set()
        for f in self.library_path.rglob("*"):
            if f.suffix.lower() in (".docx", ".pdf") and "failed-processing" not in f.parts:
                rel = str(f.relative_to(self.library_path))
                actual_files.add(rel)

        untracked = actual_files - set(processed.keys())
        for f in sorted(untracked):
            issues.append(QCIssue(
                severity=Severity.WARNING,
                category="untracked_file",
                destination="(global)",
                entity_type="file",
                entity_name=f,
                message="File exists in library but not in _processed_files",
            ))

        return issues

    def _check_duplicates(self, destinations: dict, threshold: float = 0.85) -> list[QCIssue]:
        issues = []
        for dest, data in destinations.items():
            restaurants = data.get("restaurants", [])
            names = [(i, r.get("name", "").strip().lower()) for i, r in enumerate(restaurants)]

            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    if not names[i][1] or not names[j][1]:
                        continue
                    ratio = SequenceMatcher(None, names[i][1], names[j][1]).ratio()
                    if ratio >= threshold and names[i][1] != names[j][1]:
                        issues.append(QCIssue(
                            severity=Severity.WARNING,
                            category="duplicate",
                            destination=dest,
                            entity_type="restaurant",
                            entity_name=restaurants[names[i][0]].get("name", ""),
                            message=f"~{restaurants[names[j][0]].get('name', '')} ({ratio:.0%} match)",
                        ))
        return issues

    def _check_city_attribution(self, data: dict) -> list[QCIssue]:
        issues = []
        coverage = data.get("_folder_coverage", {})

        for folder, cities in coverage.items():
            city_variants: dict[str, list[str]] = {}
            for city in cities:
                key = city.lower().replace("-", " ").replace("_", " ")
                city_variants.setdefault(key, []).append(city)

            for key, variants in city_variants.items():
                if len(variants) > 1:
                    issues.append(QCIssue(
                        severity=Severity.WARNING,
                        category="city_variant",
                        destination=folder,
                        entity_type="coverage",
                        entity_name=variants[0],
                        message=f"Duplicate city variants: {', '.join(variants)}",
                    ))

        return issues

    def _check_statistical_outliers(self, destinations: dict) -> list[QCIssue]:
        issues = []
        for dest, data in destinations.items():
            r_count = len(data.get("restaurants", []))
            a_count = len(data.get("attractions", []))

            if r_count == 0 and a_count == 0:
                issues.append(QCIssue(
                    severity=Severity.WARNING,
                    category="empty_destination",
                    destination=dest,
                    entity_type="destination",
                    entity_name=dest,
                    message="No restaurants and no attractions",
                ))
            elif r_count > 100:
                issues.append(QCIssue(
                    severity=Severity.WARNING,
                    category="outlier",
                    destination=dest,
                    entity_type="destination",
                    entity_name=dest,
                    message=f"Unusually high restaurant count: {r_count}",
                ))
        return issues

    def _check_contamination(self, destinations: dict) -> list[QCIssue]:
        """Flag entries where area/highlights/nearby_landmarks contain distances or directions."""
        issues = []
        fields_to_check = ["area", "highlights", "nearby_landmarks"]

        for dest, data in destinations.items():
            for r in data.get("restaurants", []):
                for field in fields_to_check:
                    val = r.get(field)
                    if val is None:
                        continue
                    texts = val if isinstance(val, list) else [val]
                    for text in texts:
                        if isinstance(text, str) and _CONTAMINATION_PATTERNS.search(text):
                            issues.append(QCIssue(
                                severity=Severity.WARNING,
                                category="contamination",
                                destination=dest,
                                entity_type="restaurant",
                                entity_name=r.get("name", "?"),
                                message=f"{field}: \"{text[:80]}\"",
                            ))
                            break
        return issues

    def _verify_sources(
        self, destinations: dict, sample_size: int, max_destinations: int
    ) -> list[QCIssue]:
        """Sample restaurants and verify they exist in source documents."""
        issues = []

        dest_list = sorted(
            destinations.keys(),
            key=lambda d: len(destinations[d].get("restaurants", [])),
            reverse=True,
        )[:max_destinations]

        for dest in dest_list:
            restaurants = destinations[dest].get("restaurants", [])
            if not restaurants:
                continue

            sample = random.sample(restaurants, min(sample_size, len(restaurants)))

            for r in sample:
                name = r.get("name", "")
                source_files = r.get("source_files", [])
                if not name or not source_files:
                    continue

                found = False
                for sf in source_files[:1]:
                    full_path = self.library_path / sf
                    if not full_path.exists():
                        continue
                    text = self._extract_text(full_path)
                    if not text:
                        continue
                    if name.lower() in text.lower():
                        found = True
                        break
                    parts = name.lower().split()
                    if len(parts) >= 2 and all(p in text.lower() for p in parts):
                        found = True
                        break

                if not found:
                    issues.append(QCIssue(
                        severity=Severity.CRITICAL,
                        category="hallucination",
                        destination=dest,
                        entity_type="restaurant",
                        entity_name=name,
                        message=f"Not found in source: {source_files[0] if source_files else '?'}",
                        source_file=source_files[0] if source_files else None,
                    ))

        return issues

    def _extract_text(self, path: Path) -> Optional[str]:
        try:
            if path.suffix.lower() == ".pdf":
                doc = fitz.open(str(path))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                return text
            elif path.suffix.lower() == ".docx":
                doc = Document(str(path))
                return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return None
        return None

    def _compute_score(self, issues: list[QCIssue]) -> float:
        score = 100.0
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                score -= 5
            elif issue.severity == Severity.WARNING:
                score -= 1
            else:
                score -= 0.1
        return max(0.0, round(score, 1))


def dedup_city_coverage(db_path: Path) -> int:
    """Deduplicate city names in _folder_coverage, keeping the most common capitalization."""
    index_path = db_path / "_index.json"
    if not index_path.exists():
        return 0

    data = json.loads(index_path.read_text(encoding="utf-8"))
    coverage = data.get("_folder_coverage", {})
    total_removed = 0

    for folder, cities in coverage.items():
        # Group by normalized key
        groups: dict[str, list[str]] = {}
        for city in cities:
            key = city.lower().replace("-", " ").replace("_", " ")
            groups.setdefault(key, []).append(city)

        deduped = []
        for key, variants in groups.items():
            if len(variants) > 1:
                total_removed += len(variants) - 1
            # Keep the variant with most uppercase letters (likely the "proper" one)
            best = max(variants, key=lambda v: sum(1 for c in v if c.isupper()))
            deduped.append(best)

        coverage[folder] = sorted(deduped)

    if total_removed > 0:
        data["_folder_coverage"] = coverage
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return total_removed


def dump_contamination(db_path: Path, output_path: Path) -> int:
    """Scan all shards and write contaminated highlights/area entries to a TSV."""
    rows: list[tuple[str, str, str, str]] = []

    for shard_file in sorted(db_path.glob("*.json")):
        if shard_file.name == "_index.json":
            continue
        dest = shard_file.stem
        data = json.loads(shard_file.read_text(encoding="utf-8"))

        for r in data.get("restaurants", []):
            name = r.get("name", "?")
            for field in ("highlights", "area"):
                val = r.get(field)
                if val is None:
                    continue
                texts = val if isinstance(val, list) else [val]
                for text in texts:
                    if isinstance(text, str) and _CONTAMINATION_PATTERNS.search(text):
                        rows.append((dest, name, field, text))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("destination\trestaurant\tfield\tvalue\n")
        for dest, name, field, value in rows:
            f.write(f"{dest}\t{name}\t{field}\t{value}\n")

    return len(rows)


def apply_cleanup(db_path: Path, tsv_path: Path) -> tuple[int, int]:
    """Read reviewed TSV and remove matching values from shard JSON files.

    Returns (values_removed, shards_modified).
    """
    removals: dict[str, list[tuple[str, str, str]]] = {}

    with open(tsv_path, "r", encoding="utf-8") as f:
        header = f.readline()
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 3)
            if len(parts) < 4:
                continue
            dest, name, field, value = parts
            removals.setdefault(dest, []).append((name, field, value))

    values_removed = 0
    shards_modified = 0

    for dest, entries in removals.items():
        shard_file = db_path / f"{dest}.json"
        if not shard_file.exists():
            continue

        data = json.loads(shard_file.read_text(encoding="utf-8"))
        modified = False

        removal_set = {(n, f, v) for n, f, v in entries}

        for r in data.get("restaurants", []):
            name = r.get("name", "")
            # Check highlights (list)
            if "highlights" in r and isinstance(r["highlights"], list):
                before = len(r["highlights"])
                r["highlights"] = [
                    h for h in r["highlights"]
                    if (name, "highlights", h) not in removal_set
                ]
                removed = before - len(r["highlights"])
                if removed:
                    values_removed += removed
                    modified = True

            # Check area (string)
            if "area" in r and isinstance(r["area"], str):
                if (name, "area", r["area"]) in removal_set:
                    r["area"] = None
                    values_removed += 1
                    modified = True

        if modified:
            with open(shard_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            shards_modified += 1

    return values_removed, shards_modified


def dump_duplicates(db_path: Path, output_path: Path, threshold: float = 0.85) -> int:
    """Scan all shards and write near-duplicate restaurant pairs to a TSV.

    Format: destination, keep, remove, match%
    User swaps keep/remove if needed, deletes false positive rows.
    """
    rows: list[tuple[str, str, str, str]] = []

    for shard_file in sorted(db_path.glob("*.json")):
        if shard_file.name == "_index.json":
            continue
        dest = shard_file.stem
        data = json.loads(shard_file.read_text(encoding="utf-8"))
        restaurants = data.get("restaurants", [])
        names = [(i, r.get("name", "").strip()) for i, r in enumerate(restaurants)]

        seen_pairs: set[tuple[str, str]] = set()
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if not names[i][1] or not names[j][1]:
                    continue
                ratio = SequenceMatcher(None, names[i][1].lower(), names[j][1].lower()).ratio()
                if ratio >= threshold and names[i][1].lower() != names[j][1].lower():
                    pair_key = tuple(sorted([names[i][1], names[j][1]]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    rows.append((dest, names[i][1], names[j][1], f"{ratio:.0%}"))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("destination\tkeep\tremove\tmatch\n")
        for dest, keep, remove, match in rows:
            f.write(f"{dest}\t{keep}\t{remove}\t{match}\n")

    return len(rows)


def apply_dedup(db_path: Path, tsv_path: Path) -> tuple[int, int]:
    """Read reviewed duplicates TSV and merge/remove entries from shard JSON files.

    For each row:
      - The entry matching 'remove' is deleted
      - Its must_try_dishes and source_files are merged into the survivor
      - The survivor is renamed to the 'keep' value (correct spelling)

    Returns (entries_removed, shards_modified).
    """
    removals: dict[str, list[tuple[str, str]]] = {}

    with open(tsv_path, "r", encoding="utf-8", errors="replace") as f:
        header = f.readline()
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            dest, keep, remove = parts[0], parts[1], parts[2]
            removals.setdefault(dest, []).append((keep, remove))

    entries_removed = 0
    shards_modified = 0

    for dest, pairs in removals.items():
        shard_file = db_path / f"{dest}.json"
        if not shard_file.exists():
            continue

        data = json.loads(shard_file.read_text(encoding="utf-8"))
        restaurants = data.get("restaurants", [])
        modified = False

        for keep_name, remove_name in pairs:
            keep_entry = None
            remove_idx = None

            # Find both entries — the survivor might currently have either name
            for i, r in enumerate(restaurants):
                name = r.get("name", "")
                if name == remove_name:
                    remove_idx = i
                elif name == keep_name:
                    keep_entry = r

            # If keep_name wasn't found, the survivor has the remove_name's pair
            # (user put correct spelling in keep but it was originally in remove col)
            if keep_entry is None and remove_idx is not None:
                # The "other" entry is the survivor — find it by elimination
                for i, r in enumerate(restaurants):
                    name = r.get("name", "")
                    if name != remove_name and SequenceMatcher(None, name.lower(), remove_name.lower()).ratio() >= 0.85:
                        keep_entry = r
                        break

            if remove_idx is not None:
                removed = restaurants[remove_idx]
                if keep_entry is not None:
                    # Merge data from removed into survivor
                    existing_dishes = set(keep_entry.get("must_try_dishes", []))
                    for dish in removed.get("must_try_dishes", []):
                        if dish not in existing_dishes:
                            keep_entry.setdefault("must_try_dishes", []).append(dish)

                    existing_sources = set(keep_entry.get("source_files", []))
                    for sf in removed.get("source_files", []):
                        if sf not in existing_sources:
                            keep_entry.setdefault("source_files", []).append(sf)

                    # Rename survivor to the correct spelling
                    keep_entry["name"] = keep_name

                restaurants.pop(remove_idx)
                entries_removed += 1
                modified = True

        if modified:
            data["restaurants"] = restaurants
            with open(shard_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            shards_modified += 1

    return entries_removed, shards_modified


def print_report(report: QCReport, min_severity: str = "warning") -> None:
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    min_level = severity_order.get(min_severity, 1)

    console.print()
    console.print(Panel.fit(
        "[bold]Library QC Report[/bold]",
        border_style="blue",
    ))

    console.print(f"\n  Destinations checked:  [bold]{report.destinations_checked}[/bold]")
    console.print(f"  Total restaurants:     [bold]{report.total_restaurants}[/bold]")
    console.print(f"  Total attractions:     [bold]{report.total_attractions}[/bold]")
    console.print(f"  Health Score:          [bold]{report.health_score}/100[/bold]")

    critical = [i for i in report.issues if i.severity == Severity.CRITICAL]
    warnings = [i for i in report.issues if i.severity == Severity.WARNING]
    infos = [i for i in report.issues if i.severity == Severity.INFO]

    from collections import Counter

    if critical and min_level >= 0:
        console.print(f"\n[bold red]CRITICAL ISSUES ({len(critical)})[/bold red]\n")
        for issue in critical[:50]:
            console.print(
                f"  [red]x[/red] [{issue.category}] {issue.destination} / "
                f"\"{issue.entity_name}\" — {issue.message}"
            )
        if len(critical) > 50:
            console.print(f"  [dim]… and {len(critical) - 50} more[/dim]")

    if warnings and min_level >= 1:
        cats = Counter(i.category for i in warnings)
        cat_summary = ", ".join(f"{c}: {n}" for c, n in cats.most_common())
        console.print(f"\n[bold yellow]WARNINGS ({len(warnings)})[/bold yellow]  [dim]({cat_summary})[/dim]\n")
        for issue in warnings[:50]:
            console.print(
                f"  [yellow]![/yellow] [{issue.category}] {issue.destination} / "
                f"\"{issue.entity_name}\" — {issue.message}"
            )
        if len(warnings) > 50:
            console.print(f"  [dim]… and {len(warnings) - 50} more[/dim]")

    if infos and min_level >= 2:
        console.print(f"\n[dim]INFO ({len(infos)})[/dim]\n")
        for issue in infos[:20]:
            console.print(f"  [dim]  [{issue.category}] {issue.destination} / \"{issue.entity_name}\" — {issue.message}[/dim]")

    console.print()


def print_spot_check(samples: dict[str, list[str]]) -> None:
    for field, values in samples.items():
        console.print(Rule(f"[bold]SPOT CHECK: {field}[/bold] ({len(values)} samples)"))
        console.print()
        for i, val in enumerate(values, 1):
            flagged = ""
            if _CONTAMINATION_PATTERNS.search(val):
                flagged = "  [red]<< contamination[/red]"
            elif _GENERIC_NAME_PATTERNS.match(val) and field == "name":
                flagged = "  [red]<< generic[/red]"
            console.print(f"  {i:>3}. {val}{flagged}")
        console.print()
