from __future__ import annotations
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r'^\d{1,2}\s+[a-z]{3}$', re.IGNORECASE)
_CANCELLATION_CODES = {"nr"}
_CANCELLATION_KEYWORDS = frozenset({"cancellation", "cancel", "refund"})
_MEAL_KEYWORDS = frozenset({
    "all inclusive", "full board", "half board",
    "breakfast", "bed and breakfast", "room only",
})


@dataclass
class DecodedCell:
    cancellation: str = ""
    meal_type: str = ""
    unknowns: list[str] = field(default_factory=list)


def _plain_text_fallback(value: str) -> DecodedCell:
    """Parse comma-separated plain English cancellation + meal text."""
    result = DecodedCell()
    for seg in [s.strip() for s in value.split(",") if s.strip()]:
        lower = seg.lower()
        if any(kw in lower for kw in _CANCELLATION_KEYWORDS):
            result.cancellation = seg
        elif any(kw in lower for kw in _MEAL_KEYWORDS):
            result.meal_type = seg
        else:
            result.unknowns.append(seg)
    return result


def decode_col_h(value: str | None, codes: dict[str, str]) -> DecodedCell:
    if not value:
        return DecodedCell()

    result = DecodedCell()
    segments = [s.strip() for s in str(value).strip().split(". ") if s.strip()]

    for seg in segments:
        if _DATE_RE.match(seg):
            result.cancellation = f"Free cancellation till {seg.title()}"
        elif seg.lower() in codes:
            meaning = codes[seg.lower()]
            if seg.lower() in _CANCELLATION_CODES:
                result.cancellation = meaning
            else:
                result.meal_type = meaning
        else:
            result.unknowns.append(seg)

    # If the primary decode found nothing useful, try plain-text comma split.
    if not result.cancellation and not result.meal_type and result.unknowns:
        return _plain_text_fallback(str(value).strip())

    return result
