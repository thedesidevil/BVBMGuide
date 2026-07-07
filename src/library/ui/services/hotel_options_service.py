from __future__ import annotations
import json as _json
import os as _os
import re as _re
from dataclasses import asdict

from src.hotel_options.codes import CodeStore
import src.hotel_options.enricher as _enricher
from src.hotel_options.cover_photo import fetch_cover_photo as _fetch_cover_photo
from src.hotel_options.generator import build_document
from src.hotel_options.models import Plan
from src.hotel_options.parser import parse_excel, extract_filename_meta
from src.common.ai_provider import get_ai_client
from src.library.ui.storage import StorageBackend


_NORMALIZE_LABELS_PROMPT = """\
Below is a JSON array of raw section header strings from a hotel comparison spreadsheet.
Each string may contain a location name and optionally a date range.
Clean each string as follows:
- Fix spacing around hyphens in date ranges (e.g. "Jun 28- Jul 4" → "Jun 28 - Jul 4")
- Remove extra whitespace
- Keep the date range if present — it is meaningful context for multi-stop itineraries
- Do NOT remove the parentheses around dates
Return ONLY a JSON array of strings in the same order, no other text.

Input: {labels}
"""


def _normalize_section_labels(raw_labels: list[str], ai_client) -> list[str]:
    """AI-clean raw section headers; fall back to regex on failure."""
    if not raw_labels:
        return []

    def _regex_fallback():
        # Just clean up spacing around hyphens in date ranges; keep everything else
        return [_re.sub(r'(\S)-\s*', r'\1 - ', label).strip() for label in raw_labels]

    try:
        prompt = _NORMALIZE_LABELS_PROMPT.format(labels=_json.dumps(raw_labels))
        resp = ai_client.complete(prompt).strip()
        start, end = resp.find('['), resp.rfind(']') + 1
        if start >= 0 and end > start:
            cleaned = _json.loads(resp[start:end])
            if isinstance(cleaned, list) and len(cleaned) == len(raw_labels):
                return [str(s).strip() for s in cleaned]
    except Exception:
        pass
    return _regex_fallback()


def _plan_to_dict(plan: Plan) -> dict:
    return {
        "label": plan.label,
        "hotels": [
            {
                "name": h.name,
                "category": h.category,
                "room_type": h.room_type,
                "cancellation": h.cancellation,
                "meal_type": h.meal_type,
                "dates": h.dates,
                "online_price": h.online_price,
                "customer_discount": h.customer_discount,
                "discounted_price": h.discounted_price,
                "discount_pct": h.discount_pct,
                "recommended": h.recommended,
                "why_recommend": h.why_recommend,
                "city": h.city,
            }
            for h in plan.hotels
        ],
        "pricing": {
            "total_online_price": plan.pricing.total_online_price,
            "customer_discount": plan.pricing.customer_discount,
            "discounted_price": plan.pricing.discounted_price,
            "discount_pct": plan.pricing.discount_pct,
        },
        "recommended": plan.recommended,
        "why_recommend": plan.why_recommend,
    }


_INFER_DESTINATION_PROMPT = """\
Given these section headers from a hotel accommodation spreadsheet, identify the primary travel destination.
The headers may include neighbourhood or area names — return the umbrella city or region.
Examples: "Wimbledon (Jun 28 - Jul 4)" → "London", "Shibuya (Jul 1 - Jul 5)" → "Tokyo".
Reply with just the destination name, nothing else.

Headers: {labels}
"""


def _infer_destination_from_labels(labels: list[str], ai_client) -> str:
    """Infer the primary destination from section labels; regex-strip dates as fallback."""
    import re

    def _regex_fallback() -> str:
        locations = [re.sub(r'\s*\([^)]*\)', '', label).strip() for label in labels]
        unique = list(dict.fromkeys(loc for loc in locations if loc))
        return unique[0] if unique else ""

    try:
        prompt = _INFER_DESTINATION_PROMPT.format(labels=_json.dumps(labels))
        resp = ai_client.complete(prompt).strip()
        if resp:
            return resp
    except Exception:
        pass
    return _regex_fallback()


_STAY_REQ_PROMPT = """\
The following is raw text from a travel booking spreadsheet describing stay requirements.
Extract only the stay preferences (NOT the number of travellers) and rewrite them as 2-4 short,
clean, capitalized phrases separated by " • ".
Be concise and professional. Examples of good output:
  "Breakfast Included • Free Cancellation"
  "Refundable Booking • Breakfast Included • Central Location"

Raw text: {raw}

Output only the formatted string, nothing else."""


def _format_stay_requirements(requirements: str, ai_client) -> str:
    import re
    lines = [l.strip() for l in re.split(r'[\n,]+', requirements) if l.strip()]
    stay_lines = [l for l in lines if not re.search(r'^\d+\s+adult', l, re.I)]
    if not stay_lines:
        return ""
    raw = ", ".join(stay_lines)
    try:
        return ai_client.complete(_STAY_REQ_PROMPT.format(raw=raw)).strip()
    except Exception:
        return raw


def _sheet_debug(xlsx_bytes: bytes) -> list[dict]:
    """Return first 30 rows with non-None cell values, for diagnosing parser issues."""
    import io as _io
    import openpyxl as _openpyxl
    wb = _openpyxl.load_workbook(_io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(max_row=30):
        cells = {}
        for i, cell in enumerate(row):
            if cell.value is not None:
                col = chr(ord('A') + i) if i < 26 else f"col{i}"
                cells[col] = f"{repr(cell.value)} ({type(cell.value).__name__})"
        if cells:
            rows.append({"row": row[0].row, "cells": cells})
    return rows


def parse_file(
    xlsx_bytes: bytes,
    filename: str,
    storage: StorageBackend,
    api_key: str,
) -> dict:
    codes = CodeStore(storage).load()
    result = parse_excel(xlsx_bytes, codes)
    debug_rows = _sheet_debug(xlsx_bytes)
    if not result.plans:
        return {
            "client_name": "",
            "destination": "",
            "requirements": result.requirements,
            "plans": [],
            "unknown_codes": [],
            "not_found": [],
            "maps_api_calls": 0,
            "parse_warning": (
                "No hotel rows found. Ensure hotel names are in column A "
                "and prices are numeric values in column I."
            ),
            "_debug_rows": debug_rows,
        }
    ai_client_for_labels = None
    if result.grouped_by_sections:
        ai_client_for_labels = get_ai_client()
        cleaned = _normalize_section_labels([p.label for p in result.plans], ai_client_for_labels)
        for plan, label in zip(result.plans, cleaned):
            plan.label = label
    client_name, destination = extract_filename_meta(filename)
    if result.grouped_by_sections:
        # Destination from section labels is always more reliable than the filename
        # for no-plans files (filenames often say "no plans" not a city name)
        destination = _infer_destination_from_labels(
            [p.label for p in result.plans],
            ai_client_for_labels or get_ai_client(),
        )

    unique_names = list({h.name for plan in result.plans for h in plan.hotels})
    existence_map = _enricher.check_hotels_exist(unique_names, destination, api_key)

    not_found = []
    for name, place_id in existence_map.items():
        if place_id is None:
            plan_label = next(
                (p.label for p in result.plans if any(h.name == name for h in p.hotels)),
                "",
            )
            not_found.append({"sheet_name": name, "plan_label": plan_label})

    seen_codes: set[str] = set()
    deduped_codes = []
    for u in result.unknown_codes:
        if u.code not in seen_codes:
            seen_codes.add(u.code)
            deduped_codes.append(u)

    return {
        "client_name": client_name,
        "destination": destination,
        "requirements": result.requirements,
        "plans": [_plan_to_dict(p) for p in result.plans],
        "unknown_codes": [asdict(u) for u in deduped_codes],
        "not_found": not_found,
        "maps_api_calls": len(unique_names),
        "grouped_by_sections": result.grouped_by_sections,
        "_debug_rows": debug_rows,
    }


def generate_doc(
    xlsx_bytes: bytes,
    filename: str,
    resolved_codes: dict[str, str],
    overrides: dict[str, str],
    storage: StorageBackend,
    api_key: str,
) -> bytes:
    store = CodeStore(storage)
    if resolved_codes:
        existing = store.load()
        existing.update(resolved_codes)
        store.save(existing)

    codes = store.load()
    result = parse_excel(xlsx_bytes, codes)
    if not result.plans:
        raise ValueError(
            "No hotel rows found in this file. "
            "Ensure hotel names are in column A and prices are numeric values in column I."
        )
    ai_client = get_ai_client()
    if result.grouped_by_sections:
        cleaned = _normalize_section_labels([p.label for p in result.plans], ai_client)
        for plan, label in zip(result.plans, cleaned):
            plan.label = label
    client_name, destination = extract_filename_meta(filename)
    if result.grouped_by_sections:
        destination = _infer_destination_from_labels([p.label for p in result.plans], ai_client)

    unique_names = list({h.name for plan in result.plans for h in plan.hotels})
    existence_map = _enricher.check_hotels_exist(unique_names, destination, api_key)

    for name in list(existence_map):
        if existence_map[name] is None and name in overrides:
            existence_map[name] = _enricher.place_id_from_maps_url(overrides[name])

    unparseable = [name for name in overrides if existence_map.get(name) is None]
    if unparseable:
        raise ValueError(
            f"Could not extract place_id from Maps URL for: {', '.join(unparseable)}. "
            "Please paste a full Google Maps URL containing the place details."
        )
    enriched_map = {}
    for plan in result.plans:
        for hotel in plan.hotels:
            if hotel.name in enriched_map:
                continue
            place_id = existence_map.get(hotel.name)
            if place_id:
                enriched_map[hotel.name] = _enricher.enrich_hotel(
                    hotel, place_id, destination, api_key, ai_client
                )

    travel_dates = [h.dates for plan in result.plans for h in plan.hotels if h.dates]
    destination_photo = _fetch_cover_photo(
        destination,
        travel_dates,
        ai_client,
        unsplash_key=_os.getenv("UNSPLASH_ACCESS_KEY", ""),
        pexels_key=_os.getenv("PEXELS_API_KEY", ""),
    )
    if destination_photo is None:
        destination_photo = _enricher.fetch_destination_photo(destination, api_key)
    stay_requirements = _format_stay_requirements(result.requirements, ai_client)
    docx_bytes = build_document(result.plans, enriched_map, client_name, destination,
                                result.requirements, destination_photo=destination_photo,
                                stay_requirements=stay_requirements,
                                grouped_by_sections=result.grouped_by_sections)
    enriched_count = len(enriched_map)
    maps_calls = len(unique_names) + enriched_count * 2  # Text Search + Place Details + Photo per hotel
    return docx_bytes, ai_client.cost_usd, maps_calls
