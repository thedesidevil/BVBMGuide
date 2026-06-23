from __future__ import annotations
from dataclasses import asdict

from src.hotel_options.codes import CodeStore
import src.hotel_options.enricher as _enricher
from src.hotel_options.generator import build_document
from src.hotel_options.models import Plan
from src.hotel_options.parser import parse_excel, extract_filename_meta
from src.common.ai_provider import get_ai_client
from src.library.ui.storage import StorageBackend


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
            }
            for h in plan.hotels
        ],
        "pricing": {
            "total_online_price": plan.pricing.total_online_price,
            "customer_discount": plan.pricing.customer_discount,
            "discounted_price": plan.pricing.discounted_price,
            "discount_pct": plan.pricing.discount_pct,
        },
    }


def parse_file(
    xlsx_bytes: bytes,
    filename: str,
    storage: StorageBackend,
    api_key: str,
) -> dict:
    codes = CodeStore(storage).load()
    result = parse_excel(xlsx_bytes, codes)
    client_name, destination = extract_filename_meta(filename)

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
    client_name, destination = extract_filename_meta(filename)

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

    ai_client = get_ai_client()
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

    destination_photo = _enricher.fetch_destination_photo(destination, api_key)
    docx_bytes = build_document(result.plans, enriched_map, client_name, destination,
                                result.requirements, destination_photo=destination_photo)
    enriched_count = len(enriched_map)
    maps_calls = len(unique_names) + enriched_count * 2  # Text Search + Place Details + Photo per hotel
    return docx_bytes, ai_client.cost_usd, maps_calls
