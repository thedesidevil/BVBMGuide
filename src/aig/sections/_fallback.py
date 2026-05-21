# src/aig/sections/_fallback.py
"""Shared helper: read library field, fall back to AI, write back."""

import json
from src.aig.context import AIGContext, write_back_to_library


def library_or_ai(
    context: AIGContext,
    city: str,
    library_field: str,
    ai_prompt: str,
) -> tuple[list, bool]:
    """Return (value, ai_generated). Writes back to library if AI was used."""
    lib = context.library.get(city)
    existing = getattr(lib, library_field, []) if lib else []
    if existing:
        return existing, False
    raw = context.ai_client.complete(ai_prompt, max_tokens=2048, temperature=0.3)
    # Parse: expect a JSON array of strings
    try:
        value = json.loads(raw)
        if not isinstance(value, list):
            value = [raw]
    except Exception:
        value = [raw]
    updated_by = (
        f"AI while building {', '.join(context.facts.client_names)} guide "
        f"{context.facts.trip_start_date or 'unknown date'}"
    )
    write_back_to_library(context.db_path, city, library_field, value, updated_by)
    return value, True
