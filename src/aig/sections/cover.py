import json
from src.aig.context import AIGContext

_PROMPT = """\
Generate a creative, premium travel guide title and subtitle for this trip.
Destinations: {destinations}
Dates: {start} to {end}
Client: {clients}

Return JSON: {{"title": "...", "subtitle": "..."}}
Title must be specific and evocative (e.g. "Windmills, Gelato & Ancient Ruins").
Never generic. No markdown fences."""


def build(context: AIGContext) -> dict:
    f = context.facts
    prompt = _PROMPT.format(
        destinations=", ".join(f.destinations),
        start=f.trip_start_date or "TBD",
        end=f.trip_end_date or "TBD",
        clients=", ".join(f.client_names),
    )
    raw = context.ai_client.complete(prompt, max_tokens=256, temperature=0.7)
    try:
        data = json.loads(raw)
        return {"title": data.get("title", ""), "subtitle": data.get("subtitle", "")}
    except Exception:
        fallback_title = " & ".join(f.destinations[:3]) + " — All Inclusive Guide"
        return {"title": fallback_title, "subtitle": f"{f.trip_start_date} – {f.trip_end_date}"}
