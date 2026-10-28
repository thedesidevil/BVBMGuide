"""Run the extraction prompt over one library file and merge chunk results."""

from dataclasses import dataclass
from pathlib import Path

from src.common.ai_provider import AIClient
from src.common.doc_extractor import (
    SINGLE_PASS_LIMIT,
    call_and_parse_checked,
    sanitize_text,
    split_into_chunks,
)
from src.library.ingest_core.identity import item_key, norm_key
from src.library.ingest_core.prompt import EXTRACTION_PROMPT
from src.library.ingest_core.text import UnreadableFile, read_text

MIN_TEXT_CHARS = 200


class ExtractionError(Exception):
    """The AI step failed for a file (truncated, unparseable, API error, or every chunk failed)."""


def get_ingest_client(model: str | None = None, api_key: str | None = None) -> AIClient:
    """Client for ingest runs: long timeout, one gateway retry."""
    from src.common.ai_provider import get_ai_client

    kwargs = {"api_key": api_key} if api_key else {}
    return get_ai_client(model=model, timeout=600.0, max_retries=1, **kwargs)


@dataclass
class Extraction:
    data: dict
    chunks: int
    prompt_tokens: int
    completion_tokens: int
    usd: float | None


def _scope(item: dict) -> str:
    """City scope of an item: ``city``, else the sorted ``cities`` list."""
    city = item.get("city")
    if isinstance(city, str) and city.strip():
        return norm_key(city)
    cities = item.get("cities")
    if isinstance(cities, list):
        return ",".join(sorted(norm_key(c) for c in cities if isinstance(c, str)))
    return ""


def _merge_lists(target: dict, source: dict, seen: dict[str, set], skip: set[str]) -> None:
    """Append list items from ``source`` into ``target``; first occurrence wins."""
    for name, items in source.items():
        if name in skip or not isinstance(items, list):
            continue
        out = target.setdefault(name, [])
        if not isinstance(out, list):
            continue
        keys = seen.setdefault(name, set())
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item_key(name, item)
            if key:
                full = _scope(item) + "#" + key
                if full in keys:
                    continue
                keys.add(full)
            out.append(item)


def merge_chunks(results: list[dict]) -> dict:
    """Merge per-chunk extraction results.

    First occurrence wins per ``item_key`` (scoped to the item's city);
    ``covered_cities`` and ``city_countries`` are unioned; ``country_content``
    entries are merged by normalised country name.
    """
    merged: dict = {}
    covered: list[str] = []
    city_countries: dict[str, str] = {}
    countries: dict[str, dict] = {}
    country_seen: dict[str, dict[str, set]] = {}
    seen: dict[str, set] = {}
    special = {"covered_cities", "city_countries", "country_content"}

    for r in results:
        if not isinstance(r, dict):
            continue
        cov = r.get("covered_cities")
        if isinstance(cov, list):
            for c in cov:
                if isinstance(c, str) and c.strip() and c not in covered:
                    covered.append(c)
        cc = r.get("city_countries")
        if isinstance(cc, dict):
            for city, country in cc.items():
                if isinstance(country, str) and country.strip():
                    city_countries.setdefault(city, country)
        _merge_lists(merged, r, seen, special)
        content = r.get("country_content")
        if not isinstance(content, list):
            continue
        for entry in content:
            if not isinstance(entry, dict):
                continue
            country = entry.get("country")
            if not isinstance(country, str) or not country.strip():
                continue
            ckey = norm_key(country)
            target = countries.get(ckey)
            if target is None:
                target = countries[ckey] = {"country": entry["country"]}
                country_seen[ckey] = {}
            for k, v in entry.items():
                if k != "country" and not isinstance(v, list) and v not in (None, ""):
                    target.setdefault(k, v)
            _merge_lists(target, entry, country_seen[ckey], {"country"})

    if covered:
        merged["covered_cities"] = covered
    if city_countries:
        merged["city_countries"] = city_countries
    if countries:
        merged["country_content"] = [
            {k: v for k, v in c.items() if v != []} for c in countries.values()
        ]
    return {k: v for k, v in merged.items() if v != []}


def extract_file(client: AIClient, path: Path, max_output_tokens: int = 32000) -> Extraction | None:
    """Extract library content from one file.

    Returns None when the file is unreadable or its text is under 200
    characters. Raises ``ExtractionError`` (with the reason) when the AI step
    fails: a chunk whose response was truncated, unparseable, or an API error
    (a truncated chunk is never repaired into partial data). Text up to ``SINGLE_PASS_LIMIT`` is
    sent in one call; longer text is split and the chunks merged.

    ``max_output_tokens`` is the output limit per model call; raise it to retry guides that were cut off.

    Token and cost figures are the delta of ``client.usage`` and
    ``client.cost_usd`` across this call, so they are only accurate when one
    extraction runs at a time on the client. Threaded runs sharing a client
    must account for cost themselves.
    """
    try:
        text = sanitize_text(read_text(Path(path)))
    except UnreadableFile as e:
        print(f"[extract] unreadable: {e}")
        return None
    if len(text.strip()) < MIN_TEXT_CHARS:
        return None

    pt0 = client.usage.get("prompt_tokens", 0)
    ct0 = client.usage.get("completion_tokens", 0)
    usd0 = client.cost_usd

    name = Path(path).name
    if len(text) <= SINGLE_PASS_LIMIT:
        chunks = [text]
    else:
        chunks = split_into_chunks(text)
    results = []
    failures: list[str] = []
    for i, chunk in enumerate(chunks):
        label = name if len(chunks) == 1 else f"{name} chunk {i + 1}/{len(chunks)}"
        result, reason = call_and_parse_checked(client, EXTRACTION_PROMPT.format(text=chunk), label,
                                                  max_tokens=max_output_tokens)
        if reason == "truncated":
            raise ExtractionError(f"truncated: {label} hit the output limit")
        if reason:
            failures.append(reason if len(chunks) == 1 else f"chunk {i + 1}/{len(chunks)}: {reason}")
        elif result:
            results.append(result)

    if not results:
        raise ExtractionError("; ".join(failures) or "unparseable")

    data = results[0] if len(chunks) == 1 else merge_chunks(results)
    usd1 = client.cost_usd
    usd = None if usd0 is None or usd1 is None else usd1 - usd0
    return Extraction(
        data=data,
        chunks=len(chunks),
        prompt_tokens=client.usage.get("prompt_tokens", 0) - pt0,
        completion_tokens=client.usage.get("completion_tokens", 0) - ct0,
        usd=usd,
    )
