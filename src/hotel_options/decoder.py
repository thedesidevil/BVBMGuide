from __future__ import annotations
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r'^\d{1,2}\s+[a-z]{3}$', re.IGNORECASE)
_CANCELLATION_CODES = {"nr"}


@dataclass
class DecodedCell:
    cancellation: str = ""
    meal_type: str = ""
    unknowns: list[str] = field(default_factory=list)


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

    return result
