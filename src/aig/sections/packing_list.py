import json
from src.aig.context import AIGContext

_PROMPT = """\
Create a tailored packing list for this trip.
Destinations: {destinations}
Dates: {start} to {end} (infer the season and weather)
Activities mentioned: {activities}
Dietary/cultural notes: {dietary}

Return a JSON array of packing item strings. Group logically.
Be specific to this trip — not generic. No markdown fences."""


def build(context: AIGContext) -> dict:
    f = context.facts
    all_activities = []
    for day in f.days:
        all_activities.extend(day.activities[:2])
    prompt = _PROMPT.format(
        destinations=", ".join(f.destinations),
        start=f.trip_start_date or "",
        end=f.trip_end_date or "",
        activities=", ".join(all_activities[:10]),
        dietary=", ".join(f.dietary_restrictions) or "none",
    )
    raw = context.ai_client.complete(prompt, max_tokens=1024, temperature=0.3)
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return {"items": items}
    except Exception:
        pass
    return {"items": [raw]}
