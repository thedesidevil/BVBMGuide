"""Build a structured database from the AIG library using AI extraction."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF for PDF extraction
from docx import Document
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.common.ai_provider import get_ai_client


console = Console()

DB_VERSION = "1.2"
CHECKPOINT_EVERY = 10
SINGLE_PASS_LIMIT = 120000
CHUNK_OVERLAP = 2000


def _repair_truncated_json(text: str) -> Optional[dict]:
    """Attempt to recover a valid JSON object from a truncated AI response.

    Walks the string character by character tracking nesting depth.  When we
    hit the end of the text mid-structure we close any open array, then any
    open object, and retry the parse.  Returns None if the result is still not
    parseable.
    """
    # Find the last complete top-level object close
    # Strategy: repeatedly strip the last character until json.loads succeeds,
    # then patch up unclosed containers at the structural level.

    depth: list[str] = []  # stack of '{' or '['
    in_string = False
    escape = False
    last_safe_pos = 0  # position after last fully closed top-level value

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            depth.append(ch)
        elif ch in ('}', ']'):
            if depth:
                depth.pop()
            if not depth:
                last_safe_pos = i + 1

    if in_string:
        text = text + '"'
    # If the text ends with a bare ':' (key with no value), insert null
    if text.rstrip().endswith(':'):
        text = text.rstrip() + ' null'
    # Close unclosed containers (innermost first)
    closes = {'[': ']', '{': '}'}
    text = text + ''.join(closes[c] for c in reversed(depth))

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: truncate at last known-good position
    if last_safe_pos > 0:
        candidate = text[:last_safe_pos]
        # Wrap in the outer object if we only got an array or nothing
        if not candidate.startswith('{'):
            return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def _checkpoint_save(database: dict, output_path: Path) -> None:
    """Write database to disk as an incremental checkpoint (flat or sharded)."""
    try:
        if output_path.suffix == '.json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(database, f, indent=2, ensure_ascii=False)
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            index = {k: v for k, v in database.items() if k != 'destinations'}
            with open(output_path / '_index.json', 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
            for dest, data in database['destinations'].items():
                with open(output_path / f'{dest}.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        console.print(
            f"[dim]  checkpoint saved "
            f"({len(database['_processed_files'])} files)[/dim]"
        )
    except Exception as e:
        console.print(f"[yellow]Checkpoint save failed:[/yellow] {e}")


_INCLUDED_PATTERN = re.compile(r'\bincluded\b|\bcovered\b|\bcomplementary\b|\bfree of charge\b|\bbooked\b|\bpre-booked\b', re.IGNORECASE)
_HAS_PRICE = re.compile(r'[$€£¥₹₩฿]|\b\d+\s*(USD|EUR|GBP|JPY|KZT|TRY|CHF|INR|AED|SGD|THB|MYR|IDR)\b', re.IGNORECASE)


_UNSAFE_UNICODE_RE = re.compile(r'[\U0001FA00-\U0001FFFF\U000E0000-\U000EFFFF\U000F0000-\U0010FFFF]')


def _sanitize_text(text: str) -> str:
    """Remove newer/private-use Unicode characters that API gateways may reject."""
    return _UNSAFE_UNICODE_RE.sub('', text)


def _clean_entry_fees(data: dict) -> None:
    """Remove entry_fee values that describe tour inclusions rather than real venue costs."""
    for attraction in data.get("attractions", []):
        fee = attraction.get("entry_fee")
        if fee and _INCLUDED_PATTERN.search(fee) and not _HAS_PRICE.search(fee):
            attraction.pop("entry_fee", None)


_EXTRACTION_PROMPT = """\
Extract structured travel information from this All Inclusive Guide document.

DOCUMENT:
{text}

Return a JSON object with exactly this structure:
{{
  "covered_cities": ["City1", "City2"],
  "restaurants": [
    {{
      "name": "Restaurant Name",
      "city": "Paris",
      "cuisine_type": ["Local", "Italian"],
      "price_range": "budget/mid-range/luxury or ₹/₹₹/₹₹₹",
      "hours": "Opening hours",
      "ambience": "Brief description of atmosphere",
      "area": "Neighbourhood or district where the restaurant is located",
      "nearby_landmarks": ["Eiffel Tower, Paris", "Louvre, Paris"],
      "highlights": ["Known for crispy prawns", "Has vegan options", "Popular for happy hour"],
      "must_try_dishes": ["Dish 1", "Dish 2"],
      "best_for": ["romantic", "family", "casual"],
      "vegetarian_friendly": true
    }}
  ],
  "attractions": [
    {{
      "name": "Attraction Name",
      "city": "Paris",
      "description": "Brief description",
      "hours": "Opening hours",
      "entry_fee": "Cost",
      "recommended_duration": "X hours"
    }}
  ],
  "hotels": [
    {{
      "name": "Hotel Name",
      "city": "Paris",
      "location": "Area/neighbourhood"
    }}
  ],
  "local_dishes": [
    {{
      "name": "Dish Name",
      "city": "Paris",
      "description": "What it is",
      "vegetarian": true,
      "where_to_try": "Restaurant or place name"
    }}
  ],
  "phrases": [
    {{
      "city": "France",
      "english": "Hello",
      "local": "Bonjour",
      "category": "greeting/polite/food/emergency"
    }}
  ],
  "safety_tips": [{{"cities": ["France"], "tip": "Tip text"}}],
  "souvenirs": [
    {{
      "item": "Souvenir name or type",
      "city": "Paris",
      "category": "Category (e.g. Food, Fashion, Artisan crafts, Antiques)",
      "where_to_buy": ["Shop name or market", "Area or street"]
    }}
  ],
  "emergency_contacts": [
    {{
      "city": "France",
      "service": "Police",
      "number": "17",
      "notes": "Optional extra info e.g. English-speaking, non-urgent only"
    }}
  ],
  "connectivity_tips": [{{"cities": ["France", "Switzerland"], "tip": "Tip text"}}],
  "transport_options": [
    {{
      "city": "Paris",
      "mode": "Metro",
      "description": "Brief description of the transport mode",
      "recommended_pass": "Pass or card name if applicable",
      "cost": "Price info if mentioned"
    }}
  ],
  "health_tips": [{{"cities": ["France"], "tip": "Tip text"}}]
}}

Rules:
- covered_cities: list every city, town, or tourist area this guide covers (e.g. ["Florence", "Siena", "Pisa"])
- city: REQUIRED on restaurants, attractions, hotels, local_dishes, souvenirs, emergency_contacts, transport_options, and phrases. Set to the specific city or country the item belongs to (e.g. "Paris", "Geneva", "France"). Determine from section headings like "Restaurants in Zurich", "Day 3 – Florence", or explicit mentions in the text. Never leave blank
- cities: REQUIRED on safety_tips, connectivity_tips, and health_tips. A LIST of every city or country the tip applies to. If a tip says "this SIM card works in France, Switzerland and Italy" set cities to ["France", "Switzerland", "Italy"]. If a tip is country-wide for one country set cities to that country name alone e.g. ["France"]. Never leave empty
- Extract ALL restaurants mentioned, not just a few
- Include all details provided (hours, prices, dishes)
- area: the neighbourhood, district, or zone where the restaurant is located. Infer from: (1) section headings like "Dinner Options in Chamonix Town Centre" or "Restaurants near the Louvre"; (2) explicit mentions like "located in Gare de Lyon station", "in the Marais district". Omit if no area context is available
- nearby_landmarks: list of specific attractions, monuments, or landmarks mentioned in proximity to this restaurant. Extract from phrases like "near Eiffel Tower", "5 mins walk from Monet Garden", "option before/after Sacre Coeur", "opposite the Louvre". Only include landmarks explicitly stated — do not infer. Always append the city name when it can be determined from context — e.g. "Eiffel Tower, Paris" or "Monet Garden, Giverny" or "Colosseum, Rome". This is especially important for multi-city guides
- highlights: short factual callouts about the restaurant itself — e.g. "Known for seafood", "Has vegan options", "Good for happy hour", "Serves veg and non-veg buffet", "Only open for dinner". Only include facts about the restaurant explicitly stated in the text. NEVER include any travel time, distance, or directions of any kind (e.g. "5 min walk", "15 min metro ride", "10 min from X", "2 km away", "close to the hotel") — a highlight describes the restaurant, not how to reach it
- vegetarian_friendly: set to true ONLY if the document explicitly states the restaurant has vegetarian or vegan options (e.g. "veg-friendly", "vegan options", "serves vegetarian", "has veg menu"). If the document does not mention it, omit this field entirely — do not set it to false, as that implies we checked and it is not vegetarian-friendly when we simply do not know. NEVER infer from cuisine type
- entry_fee: only include actual costs payable at the venue (e.g. "200 KZT", "$10 USD"). Omit if the value says "included in tour/package", "already included", "tickets are covered", "already booked", "pre-booked", or similar — those are client-specific and not reusable
- souvenirs: extract from any souvenir or shopping section regardless of format — (1) old tabular format with columns "Type of souvenir", "Category", "Where to buy"; (2) new heading-based format with sections like "What to Buy", "Where to Buy", or combined "What to Buy and from where". Map each item to the item/category/where_to_buy fields. where_to_buy should be a list of shop names, markets, streets, or areas mentioned
- emergency_contacts: extract every emergency number explicitly stated — police, ambulance, fire, tourist police, coast guard, embassy hotline. Include service name, number, and any notes (e.g. "English-speaking", "for non-urgent matters"). Omit this field entirely if no numbers are stated
- connectivity_tips: extract tips about local SIM cards, eSIM options, mobile data plans, WiFi availability, recommended providers, and approximate costs. One tip per list item. Omit if no connectivity info is present
- transport_options: extract each mode of transport mentioned (metro, bus, tram, taxi, tuk-tuk, ferry, ride-share app). Include description, recommended pass or card name (e.g. "Navigo card", "Oyster card"), and cost if stated. Omit recommended_pass and cost fields if not mentioned
- health_tips: extract vaccination requirements, recommended vaccinations, health precautions, travel insurance advice, and medical facility information. One tip per list item. Omit if no health info is present
- If a field is not present, omit it or use null
- Return ONLY valid JSON, no explanation"""


class LibraryBuilder:
    """Builds a structured database from the AIG library using AI."""

    def __init__(
        self,
        library_path: str | Path,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        workers: int = 5,
    ):
        self.library_path = Path(library_path)
        self.workers = workers
        self.client = get_ai_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    def build_database(self, output_path: Optional[Path] = None, force: bool = False, workers: Optional[int] = None) -> dict:
        """Build or incrementally update the library database.

        Scans all DOCX/PDF files in subfolders of library_path.
        Skips files whose relative-path key is already in _processed_files
        with an unchanged mtime (unless force=True).
        """
        if output_path is None:
            output_path = Path("library_db")

        existing_db = None
        processed_files: dict = {}

        if output_path.exists() and not force:
            try:
                if output_path.suffix == '.json':
                    with open(output_path, 'r', encoding='utf-8') as f:
                        existing_db = json.load(f)
                else:
                    index_path = output_path / '_index.json'
                    if index_path.exists():
                        with open(index_path, 'r', encoding='utf-8') as f:
                            existing_db = json.load(f)
                processed_files = existing_db.get("_processed_files", {})
                console.print(f"[dim]Found existing database with {len(processed_files)} processed files[/dim]")
            except Exception:
                existing_db = None

        database: dict = {
            "version": DB_VERSION,
            "built_at": datetime.now().isoformat(),
            "destinations": existing_db.get("destinations", {}) if existing_db else {},
            "_processed_files": processed_files,
            "_folder_coverage": existing_db.get("_folder_coverage", {}) if existing_db else {},
        }
        if existing_db and "_review_status" in existing_db:
            database["_review_status"] = existing_db["_review_status"]

        # Discover all DOCX/PDF files (skip failed-processing/)
        all_files = [
            f for f in self.library_path.rglob("*")
            if f.suffix.lower() in (".docx", ".pdf")
            and "failed-processing" not in f.parts
        ]

        # Determine which files need processing
        files_to_process = []
        for file_path in all_files:
            rel_key = str(file_path.relative_to(self.library_path))
            file_mtime = os.path.getmtime(file_path)
            if rel_key in processed_files and processed_files[rel_key].get("mtime") == file_mtime:
                continue
            files_to_process.append(file_path)

        if not files_to_process:
            console.print("\n[green]✓ All files already processed. Database is up to date.[/green]")
            self._build_folder_coverage(database)
            return database

        num_workers = workers if workers is not None else self.workers

        console.print(f"\n[bold]Building library database...[/bold]")
        console.print(f"  Total files in library: {len(all_files)}")
        console.print(f"  Already processed:      {len(all_files) - len(files_to_process)}")
        console.print(f"  To process:             {len(files_to_process)}")
        console.print(f"  Workers:                {num_workers}\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing files...", total=len(files_to_process))

            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_to_file = {
                    executor.submit(self._process_file, fp): fp
                    for fp in files_to_process
                }

                completed_since_checkpoint = 0
                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    rel_key = str(file_path.relative_to(self.library_path))
                    destination = file_path.parent.name

                    progress.update(task, description=f"[{destination}] {file_path.name[:35]}...")

                    try:
                        file_data = future.result()
                        if file_data:
                            file_mtime = os.path.getmtime(file_path)
                            tracked_dests: set[str] = set()

                            _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips"}

                            for field in ("restaurants", "attractions", "hotels",
                                          "local_dishes", "phrases", "safety_tips", "souvenirs",
                                          "emergency_contacts", "connectivity_tips",
                                          "transport_options", "health_tips"):
                                for item in file_data.get(field) or []:
                                    if isinstance(item, dict):
                                        item["_source_file"] = rel_key
                                        item["_source_mtime"] = file_mtime
                                        if field in _MULTI_CITY_FIELDS:
                                            raw = item.get("cities") or [item.get("city", "")]
                                            dests = [c.strip().title() for c in raw if c and c.strip()] or [destination]
                                        else:
                                            raw_city = item.get("city", "").strip()
                                            dests = [raw_city.title() if raw_city else destination]
                                    else:
                                        dests = [destination]

                                    for dest in dests:
                                        if dest not in database["destinations"]:
                                            database["destinations"][dest] = {
                                                "restaurants": [], "attractions": [], "hotels": [],
                                                "local_dishes": [], "phrases": [], "safety_tips": [],
                                                "souvenirs": [], "emergency_contacts": [],
                                                "connectivity_tips": [], "transport_options": [],
                                                "health_tips": [], "source_files": [],
                                            }

                                        dest_data = database["destinations"][dest]
                                        if dest not in tracked_dests:
                                            if rel_key not in dest_data["source_files"]:
                                                dest_data["source_files"].append(rel_key)
                                            tracked_dests.add(dest)

                                        dest_data[field].append(item)

                            database["_processed_files"][rel_key] = {
                                "mtime": file_mtime,
                                "destination": destination,
                                "covered_cities": file_data.get("covered_cities", []),
                                "processed_at": datetime.now().isoformat(),
                            }

                    except Exception as e:
                        console.print(f"[yellow]Warning:[/yellow] Failed to process {rel_key}: {e}")

                    progress.advance(task)
                    completed_since_checkpoint += 1
                    if completed_since_checkpoint >= CHECKPOINT_EVERY:
                        _checkpoint_save(database, output_path)
                        completed_since_checkpoint = 0

        # Deduplicate
        for dest_data in database["destinations"].values():
            dest_data["restaurants"] = self._deduplicate_by_name(dest_data["restaurants"])
            dest_data["attractions"] = self._deduplicate_by_name(dest_data["attractions"])
            dest_data["local_dishes"] = self._deduplicate_by_name(dest_data["local_dishes"])

        self._build_folder_coverage(database)

        # Reset review status to pending for any cities that were rebuilt
        affected_cities = {
            meta.get("destination", "")
            for rel_key, meta in database["_processed_files"].items()
            if rel_key in {str(fp.relative_to(self.library_path)) for fp in files_to_process}
        }
        review_status = database.get("_review_status", {})
        if review_status:
            for city in affected_cities:
                if city in review_status:
                    review_status[city] = {"status": "pending"}
            database["_review_status"] = review_status

        _checkpoint_save(database, output_path)

        console.print(f"\n[bold green]✓ Database saved to {output_path}[/bold green]")
        self._print_summary(database)
        return database

    def process_single_file(self, file_path: Path, destination: str, database: dict) -> bool:
        """Process one file and merge its data into database in-place. Returns True on success."""
        rel_key = str(file_path.relative_to(self.library_path))

        try:
            file_data = self._process_file(file_path)
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to process {rel_key}: {e}")
            return False

        if not file_data:
            return False

        file_mtime = os.path.getmtime(file_path)
        tracked_dests: set[str] = set()
        _MULTI_CITY_FIELDS = {"safety_tips", "connectivity_tips", "health_tips"}

        for field in ("restaurants", "attractions", "hotels",
                      "local_dishes", "phrases", "safety_tips", "souvenirs",
                      "emergency_contacts", "connectivity_tips",
                      "transport_options", "health_tips"):
            for item in file_data.get(field) or []:
                if isinstance(item, dict):
                    item["_source_file"] = rel_key
                    item["_source_mtime"] = file_mtime
                    if field in _MULTI_CITY_FIELDS:
                        raw = item.get("cities") or [item.get("city", "")]
                        dests = [c.strip().title() for c in raw if c and c.strip()] or [destination]
                    else:
                        raw_city = item.get("city", "").strip()
                        dests = [raw_city.title() if raw_city else destination]
                else:
                    dests = [destination]

                for dest in dests:
                    if dest not in database["destinations"]:
                        database["destinations"][dest] = {
                            "restaurants": [], "attractions": [], "hotels": [],
                            "local_dishes": [], "phrases": [], "safety_tips": [],
                            "souvenirs": [], "emergency_contacts": [],
                            "connectivity_tips": [], "transport_options": [],
                            "health_tips": [], "source_files": [],
                        }

                    dest_data = database["destinations"][dest]
                    if dest not in tracked_dests:
                        if rel_key not in dest_data["source_files"]:
                            dest_data["source_files"].append(rel_key)
                        tracked_dests.add(dest)

                    dest_data[field].append(item)

        database["_processed_files"][rel_key] = {
            "mtime": file_mtime,
            "destination": destination,
            "covered_cities": file_data.get("covered_cities", []),
            "processed_at": datetime.now().isoformat(),
        }

        self._build_folder_coverage(database)
        return True

    def _process_file(self, file_path: Path) -> Optional[dict]:
        """Extract structured data from one DOCX or PDF file via AI."""
        try:
            if file_path.suffix.lower() == '.pdf':
                full_text = self._extract_text_from_pdf(file_path)
            else:
                full_text = self._extract_text_from_docx(file_path)
        except Exception as e:
            console.print(f"[dim]Text extraction failed for {file_path.name}: {e}[/dim]")
            return None

        full_text = _sanitize_text(full_text)

        if len(full_text) < 200:
            return None

        if len(full_text) <= SINGLE_PASS_LIMIT:
            prompt = _EXTRACTION_PROMPT.format(text=full_text)
            result = self._call_and_parse(prompt, file_path.name)
            return result

        # Multi-pass chunked extraction for large documents
        chunks = self._split_into_chunks(full_text)
        console.print(f"[dim]{file_path.name}: {len(full_text):,} chars → {len(chunks)} chunks[/dim]")

        chunk_results = []
        for i, chunk in enumerate(chunks):
            prompt = _EXTRACTION_PROMPT.format(text=chunk)
            result = self._call_and_parse(prompt, f"{file_path.name} chunk {i+1}/{len(chunks)}")
            if result:
                chunk_results.append(result)

        if not chunk_results:
            console.print(f"[dim]AI extraction failed for {file_path.name}: all chunks failed[/dim]")
            return None

        if len(chunk_results) == 1:
            return chunk_results[0]

        return self._merge_extraction_results(chunk_results)

    def _call_and_parse(self, prompt: str, label: str) -> Optional[dict]:
        """Send prompt to AI and parse the JSON response."""
        try:
            raw = self.client.complete(prompt, max_tokens=32000)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = _repair_truncated_json(raw)
                if not result:
                    console.print(f"[dim]JSON parse failed for {label}[/dim]")
                    return None
            _clean_entry_fees(result)
            return result
        except Exception as e:
            console.print(f"[dim]AI extraction failed for {label}: {e}[/dim]")
            return None

    def _split_into_chunks(self, text: str, max_chunk_size: int = SINGLE_PASS_LIMIT, overlap: int = CHUNK_OVERLAP) -> list[str]:
        """Split text into chunks, preferring paragraph boundaries."""
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break

            # Try to split at a paragraph boundary within the last 5K chars
            split_zone_start = end - 5000
            split_zone = text[split_zone_start:end]
            last_para_break = split_zone.rfind("\n\n")

            if last_para_break != -1:
                end = split_zone_start + last_para_break
            else:
                last_newline = split_zone.rfind("\n")
                if last_newline != -1:
                    end = split_zone_start + last_newline

            chunks.append(text[start:end])
            start = end - overlap

        return chunks

    _DEDUP_KEYS = {
        "restaurants": "name",
        "attractions": "name",
        "hotels": "name",
        "local_dishes": "name",
        "phrases": "english",
        "safety_tips": "tip",
        "souvenirs": "item",
        "emergency_contacts": "number",
        "connectivity_tips": "tip",
        "transport_options": "mode",
        "health_tips": "tip",
    }

    def _merge_extraction_results(self, results: list[dict]) -> dict:
        """Merge multiple chunk extraction results, deduplicating by field-specific keys."""
        merged: dict = {}

        # covered_cities: union
        all_cities: list[str] = []
        for r in results:
            for city in (r.get("covered_cities") or []):
                if city not in all_cities:
                    all_cities.append(city)
        merged["covered_cities"] = all_cities

        for field, key in self._DEDUP_KEYS.items():
            combined: list[dict] = []
            seen: set[str] = set()
            for r in results:
                for item in (r.get(field) or []):
                    if not isinstance(item, dict):
                        continue
                    if field == "transport_options":
                        dedup_val = (item.get("city", "").lower().strip() + "|" +
                                     item.get(key, "").lower().strip())
                    else:
                        dedup_val = item.get(key, "").lower().strip()
                    if dedup_val and dedup_val in seen:
                        continue
                    if dedup_val:
                        seen.add(dedup_val)
                    combined.append(item)
            if combined:
                merged[field] = combined

        return merged

    def _extract_text_from_docx(self, docx_path: Path) -> str:
        doc = Document(docx_path)
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        doc = fitz.open(pdf_path)
        text_parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(text_parts)

    def _build_folder_coverage(self, database: dict) -> None:
        """Build _folder_coverage by unioning covered_cities across all processed files per folder."""
        coverage: dict[str, set] = {}
        for meta in database["_processed_files"].values():
            folder = meta.get("destination", "")
            cities = meta.get("covered_cities", [])
            if folder:
                coverage.setdefault(folder, set()).update(c.strip() for c in cities if c.strip())
        database["_folder_coverage"] = {f: sorted(cities) for f, cities in coverage.items()}

    def _deduplicate_by_name(self, items: list) -> list:
        """Deduplicate items by name with recency-aware merging.

        - must_try_dishes: always unioned across all source files
        - all other fields: overwritten only if the incoming file is newer
        - source_files: accumulated list of every file the item appeared in
        """
        seen: dict[str, dict] = {}
        for item in items:
            name = item.get("name", "").lower().strip()
            if not name:
                continue
            src_file = item.get("_source_file")
            src_mtime = item.get("_source_mtime", 0)

            if name not in seen:
                seen[name] = item.copy()
                seen[name]["source_files"] = [src_file] if src_file else []
            else:
                existing = seen[name]

                if src_file and src_file not in existing["source_files"]:
                    existing["source_files"].append(src_file)

                # Always union must_try_dishes
                existing_dishes = existing.get("must_try_dishes") or []
                new_dishes = item.get("must_try_dishes") or []
                merged = list(dict.fromkeys(existing_dishes + [d for d in new_dishes if d not in existing_dishes]))
                if merged:
                    existing["must_try_dishes"] = merged

                # Overwrite other fields only if incoming file is newer
                if src_mtime > existing.get("_source_mtime", 0):
                    for key, value in item.items():
                        if key in ("must_try_dishes", "_source_file", "_source_mtime", "source_files"):
                            continue
                        if value is not None:
                            existing[key] = value
                    existing["_source_mtime"] = src_mtime

        result = []
        for item in seen.values():
            item.pop("_source_file", None)
            item.pop("_source_mtime", None)
            result.append(item)
        return result

    def _print_summary(self, database: dict) -> None:
        console.print("\n[bold]Library Database Summary[/bold]\n")
        for dest, data in sorted(database["destinations"].items()):
            cities = database.get("_folder_coverage", {}).get(dest, [])
            console.print(f"  [cyan]{dest}[/cyan]")
            console.print(f"    Files:       {len(data['source_files'])}")
            console.print(f"    Restaurants: {len(data['restaurants'])}")
            console.print(f"    Attractions: {len(data['attractions'])}")
            console.print(f"    Cities:      {', '.join(cities[:5])}{'...' if len(cities) > 5 else ''}")
            console.print()


class LibraryDatabase:
    """Query interface for the pre-built library database.

    Auto-detects format: if db_path ends in '.json' → flat legacy file;
    otherwise → sharded directory with _index.json + per-destination files.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._sharded = self.db_path.suffix != '.json'
        self._data: Optional[dict] = None       # flat mode full dict, or sharded full reconstruction
        self._index: Optional[dict] = None      # sharded mode: index only
        self._dest_cache: dict[str, dict] = {}  # sharded mode: lazily loaded destination files

    def load(self) -> None:
        if not self._sharded:
            if not self.db_path.exists():
                raise FileNotFoundError(f"Library database not found: {self.db_path}")
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
        else:
            index_path = self.db_path / '_index.json'
            if not index_path.exists():
                raise FileNotFoundError(f"Library database not found: {self.db_path}")
            with open(index_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)

    def _load_dest(self, dest: str) -> dict:
        """Load and cache one destination shard."""
        if dest not in self._dest_cache:
            dest_path = self.db_path / f'{dest}.json'
            if dest_path.exists():
                with open(dest_path, 'r', encoding='utf-8') as f:
                    self._dest_cache[dest] = json.load(f)
            else:
                self._dest_cache[dest] = {}
        return self._dest_cache[dest]

    @property
    def data(self) -> dict:
        """Return full database dict — loads all shards if needed (used by stats/verify)."""
        if self._data is None:
            if self._index is None:
                self.load()
            if self._sharded:
                self._data = dict(self._index)
                self._data['destinations'] = {}
                for dest_file in sorted(self.db_path.glob('*.json')):
                    if dest_file.name == '_index.json':
                        continue
                    with open(dest_file, 'r', encoding='utf-8') as f:
                        self._data['destinations'][dest_file.stem] = json.load(f)
        return self._data

    def get_destinations(self) -> list[str]:
        if self._sharded:
            if self._index is None:
                self.load()
            return list(self._index.get('_folder_coverage', {}).keys())
        return list(self.data['destinations'].keys())

    def find_relevant_folders(self, cities: list[str]) -> dict[str, list[str]]:
        """Return {destination: [source_files]} for destinations matching any of the given cities.

        Checks city-named destination shards directly first (primary path after city routing),
        then falls back to _folder_coverage for any cities not directly matched.
        """
        if self._sharded and self._index is None:
            self.load()
        cities_lower = {c.lower().strip() for c in cities}
        result = {}

        # Primary: direct city-shard match (destinations are now city names)
        for dest in self.get_destinations():
            if dest.lower() in cities_lower:
                dest_data = self._load_dest(dest) if self._sharded else self.data['destinations'].get(dest, {})
                result[dest] = dest_data.get('source_files', [])

        # Fallback: folder coverage index (catches cities stored under a country shard)
        unmatched = cities_lower - {d.lower() for d in result}
        if unmatched:
            coverage = (self._index if self._sharded else self.data).get('_folder_coverage', {})
            for folder, covered in coverage.items():
                if unmatched & {c.lower() for c in covered}:
                    if folder not in result:
                        dest_data = self._load_dest(folder) if self._sharded else self.data['destinations'].get(folder, {})
                        result[folder] = dest_data.get('source_files', [])

        return result

    def get_restaurants(self, destination: str) -> list[dict]:
        dest_lower = destination.lower()
        if self._sharded:
            if self._index is None:
                self.load()
            for dest in self._index.get('_folder_coverage', {}):
                if dest.lower() == dest_lower:
                    return self._load_dest(dest).get('restaurants', [])
            return []
        for dest, data in self.data['destinations'].items():
            if dest.lower() == dest_lower:
                return data.get('restaurants', [])
        return []
