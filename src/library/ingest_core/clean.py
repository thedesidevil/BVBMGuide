"""Clean AI extraction output before it is merged into the library."""

import copy
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .identity import IDENTITY_FIELDS, item_key

# VERIFY and CHECK: are uppercase-only (as v2 renders them) so ordinary tips are not dropped.
MARKER_RE = re.compile(r"⚠|(?i:ADD RESTAURANT|PRICE UNKNOWN|WRITE PERSONAL LETTER)|\bVERIFY\b|CHECK:")
CHATTER_RE = re.compile(r"\bI would recommend\b|\bI['’]d (?:aim|keep|suggest|skip|treat|choose)\b|\bHere are clear\b|"
                        r"\bin your preferred format\b|\bLet me know if\b|\bas an AI\b", re.I)
CLIENT_RE = re.compile(r"\b(?:booking|confirmation|reservation) (?:ref(?:erence)?\b|number\b|no(?:\.(?=\s|$|\d)|\s*\d|:)|id\b)", re.I)
_DAY_START_RE = re.compile(r"^\s*Day \d+", re.I)


def is_v2_generated(path: Path) -> bool:
    """True when the docx carries a `bvbm_run_id` custom property (made by AIG v2)."""
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("docProps/custom.xml"))
        return any(el.get("name") == "bvbm_run_id" for el in root.iter() if el.tag.endswith("property"))
    except Exception:
        return False


def _strings(item: dict) -> list[str]:
    out = []
    for v in item.values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.append(" ".join(str(x) for x in v))
    return out


def _reason(list_name: str, item) -> str:
    if not isinstance(item, dict):
        return "no_identity"
    texts = _strings(item)
    if any(MARKER_RE.search(t) for t in texts):
        return "marker"
    if any(CHATTER_RE.search(t) for t in texts):
        return "chatter"
    if any(CLIENT_RE.search(t) or _DAY_START_RE.search(t) for t in texts):
        return "client_specific"
    if not item_key(list_name, item):
        return "no_identity"
    return ""


def _clean_lists(container: dict, dropped: list[dict], scope: str = "") -> None:
    for name in IDENTITY_FIELDS:
        items = container.get(name)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            reason = _reason(name, item)
            if reason:
                text = " | ".join(_strings(item)) if isinstance(item, dict) else str(item)
                rec = {"list": name, "reason": reason, "text": text}
                if scope:
                    rec["scope"] = scope
                dropped.append(rec)
            else:
                kept.append(item)
        container[name] = kept


def clean_extraction(data: dict) -> tuple[dict, list[dict]]:
    """Return (cleaned deep copy, dropped items). The input is never mutated."""
    out = copy.deepcopy(data)
    dropped: list[dict] = []
    _clean_lists(out, dropped)
    cc = out.get("country_content")
    if isinstance(cc, list):  # the shape EXTRACTION_PROMPT emits: [{country, <lists>}]
        for entry in cc:
            if isinstance(entry, dict):
                country = entry.get("country")
                scope = f"_country/{country}" if isinstance(country, str) and country.strip() else "_country/"
                _clean_lists(entry, dropped, scope)
    elif isinstance(cc, dict):  # tolerated legacy shape: {country: {lists}}
        for country, entry in cc.items():
            if isinstance(entry, dict):
                _clean_lists(entry, dropped, f"_country/{country}")
    return out, dropped
