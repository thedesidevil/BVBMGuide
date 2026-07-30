from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r'^\d{1,2}\s+[a-z]{3}$', re.IGNORECASE)
_CANCELLATION_CODES = {"nr"}

_BATCH_SYSTEM = """\
You are parsing hotel booking notes from a travel spreadsheet.
Each entry is the raw text from the b2b policy column (column H) and may contain a \
room description, a cancellation policy, and a meal type indicator.
For each entry extract:
- "cancellation": the cancellation policy as a clean sentence \
(e.g. "Free cancellation until 15 Oct", "Non-refundable", \
"Free cancellation before 14 Oct 11:58 PM"). Empty string if not mentioned.
- "meal_type": the meal plan included (e.g. "Breakfast included", "Room only"). \
Empty string if not mentioned.
Return a JSON object: {"results": [{"cancellation": "...", "meal_type": "..."}, ...]} \
in the same order as the input. Never omit entries."""

_BATCH_PROMPT = "Parse these hotel booking notes:\n\n{entries}"


@dataclass
class DecodedCell:
    cancellation: str = ""
    meal_type: str = ""
    unknowns: list[str] = field(default_factory=list)


def _try_shortcode(value: str, codes: dict) -> DecodedCell | None:
    """Decode a short-code style value (e.g. '6 sep. br'). Returns None if any segment is unrecognized."""
    result = DecodedCell()
    for seg in [s.strip() for s in value.strip().split(". ") if s.strip()]:
        if _DATE_RE.match(seg):
            result.cancellation = f"Free cancellation till {seg.title()}"
        elif seg.lower() in codes:
            meaning = codes[seg.lower()]
            if seg.lower() in _CANCELLATION_CODES:
                result.cancellation = meaning
            else:
                result.meal_type = meaning
        else:
            return None
    return result


def batch_decode_col_h(
    values: list[str | None],
    codes: dict,
    ai_client,
) -> list[DecodedCell]:
    """Decode a batch of col H values. Fast-paths known short codes; sends free text to AI in one call."""
    results: list[DecodedCell | None] = [None] * len(values)
    ai_indices: list[int] = []
    ai_values: list[str] = []

    for i, val in enumerate(values):
        if not val:
            results[i] = DecodedCell()
            continue
        decoded = _try_shortcode(val, codes)
        if decoded is not None:
            results[i] = decoded
        else:
            ai_indices.append(i)
            ai_values.append(str(val))

    if ai_indices and ai_client is not None:
        try:
            prompt = _BATCH_PROMPT.format(entries=json.dumps(ai_values, ensure_ascii=False))
            raw = ai_client.complete_json(prompt, system=_BATCH_SYSTEM)
            # Strip markdown code fences if the model wrapped its response
            start = raw.find('{')
            end = raw.rfind('}') + 1
            raw = raw[start:end] if start >= 0 and end > start else raw
            ai_results = json.loads(raw).get("results", [])
            for j, idx in enumerate(ai_indices):
                if j < len(ai_results):
                    r = ai_results[j]
                    results[idx] = DecodedCell(
                        cancellation=str(r.get("cancellation") or "").strip(),
                        meal_type=str(r.get("meal_type") or "").strip(),
                    )
                else:
                    results[idx] = DecodedCell()
        except Exception:
            for idx in ai_indices:
                results[idx] = DecodedCell()
    else:
        for idx in ai_indices:
            results[idx] = DecodedCell()

    return [r if r is not None else DecodedCell() for r in results]
