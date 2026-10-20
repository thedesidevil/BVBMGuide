import json

from ..llm import StepLLM
from ..models import TripPlan
from .attachments import Attachment
from .template import IntakeFields

SYSTEM_PROMPT = """You extract a structured trip plan for a travel agency from the team's intake form and attachments. Return ONLY a JSON object that matches the schema given in the user message.

ACCURACY IS PARAMOUNT. Never invent facts. Include only hotels, flights, trains, attractions, activities, times, dates, confirmation numbers and names that appear in the inputs. If something is not stated, leave it empty or omit it; never fill a gap with something plausible.

Source of truth when inputs disagree: BVM service vouchers and tickets > planner notes > itinerary documents. This applies to hotels, flight and train times, and check-in/check-out dates. Set HotelStay.source to "voucher", "notes" or "itinerary" accordingly.

Rules:
- Every either/or or conditional choice (for example "Broadway show or Top of the Rock", "if the weather is good ...") becomes an entry in open_choices with the day, the text, and each option. Do not pick one for the client and do not put the choice into a day's items.
- A day such as "Choose your day trip" or "free day, decide later" is vague: add its date to vague_days and keep its items empty.
- Planner-to-team commentary (notes addressed to colleagues, reminders, internal instructions, "please check ...") goes verbatim into commentary_removed. It must never appear in items, titles or notes.
- meal_rules capture explicit meal phrases for that day verbatim (for example "Lunch near the ferry", "dinner at the hotel").
- Items the notes call "optional" get optional=true.
- A Booking is created only from an attachment (voucher, ticket, confirmation). "Confirmed" in the notes without an attachment stays a PlannedItem, not a Booking.
- Service vouchers: read the passenger table, flights (free text such as "MIDNIGHT ARRIVAL AT 00:10 ON 25 SEPTEMBER (NIGHT OF 24 SEPTEMBER)" means arrival 00:10 on 25 September), the hotel table (city, hotel, check-in, check-out, confirmation notes) and the day-wise blocks (type, time window, pickup/checkout times, notes). Turn services into Booking or PlannedItem with included_in_package=true for Bookings. Ignore stray document headings such as a leftover destination name.
- Meal plans: "Breakfast included" -> meal_plan "breakfast"; "half board" -> "half_board"; "full board" -> "full_board"; "all meals", "all inclusive" -> "all_inclusive". For a single included meal on an activity (for example "BBQ dinner included") set PlannedItem.includes_meal.
- Cruise nights and sleeper-train nights become HotelStay with kind "cruise" or "sleeper_train".
- "Pure veg" wording sets diet.pure_veg=true (and add "vegetarian" to restrictions).
- Drive-day stops named in the inputs become drive_stops on that day.
- Per-passenger tickets: legs with the same ref, flight/train number and departure are ONE leg; list it once (pax_label may list the passengers).
- Dates are ISO (YYYY-MM-DD); if the year is missing, infer it only from other dated inputs. Times are 24h.
- trip_scope is "domestic" only when the whole trip stays within the client's home country India, else "international".
- Attachments listed as image-only could not be read; do not guess their content.
"""


def validate_trip(plan: TripPlan) -> list[str]:
    problems: list[str] = []
    if not plan.days:
        problems.append("no days extracted")
    for h in plan.hotels:
        if h.check_out <= h.check_in:
            problems.append(f"hotel '{h.hotel}' check_out {h.check_out} is not after check_in {h.check_in}")
    seen = set()
    for d in plan.days:
        if d.date in seen:
            problems.append(f"duplicate day date {d.date}")
        seen.add(d.date)
    if plan.hotels:
        lo = min(h.check_in for h in plan.hotels)
        hi = max(h.check_out for h in plan.hotels)
        for d in plan.days:
            if not lo <= d.date <= hi:
                problems.append(f"day {d.date} is outside the hotel stays {lo} to {hi}")
    return problems


def dedupe_legs(plan: TripPlan) -> TripPlan:
    legs = []
    index: dict[tuple, int] = {}
    for leg in plan.transport:
        if not (leg.ref or leg.number):
            legs.append(leg)
            continue
        key = (leg.ref, leg.number, leg.depart)
        if key in index:
            kept = legs[index[key]]
            if leg.pax_label and leg.pax_label not in kept.pax_label.split(", "):
                legs[index[key]] = kept.model_copy(update={
                    "pax_label": ", ".join(p for p in [kept.pax_label, leg.pax_label] if p)})
            continue
        index[key] = len(legs)
        legs.append(leg)
    return plan.model_copy(update={"transport": legs})


def _build_prompt(intake: IntakeFields | None, attachments: list[Attachment]) -> str:
    parts = ["JSON schema of the TripPlan to return:", json.dumps(TripPlan.model_json_schema())]
    if intake is not None:
        parts.append("\n=== INTAKE FORM VALUES ===")
        parts.extend(f"{k}: {v}" for k, v in intake.values.items())
        if intake.see_attachments:
            parts.append("Fields answered 'see attachments': " + ", ".join(sorted(intake.see_attachments)))
    usable = [a for a in attachments if not a.duplicate_of and not a.error]
    for a in usable:
        if a.image_only:
            parts.append(f"\n=== ATTACHMENT: {a.name} (image-only, unreadable, no text available) ===")
        else:
            parts.append(f"\n=== ATTACHMENT: {a.name} ===\n{a.text}")
    parts.append("\nReturn the TripPlan as JSON.")
    return "\n".join(parts)


def extract_trip(intake: IntakeFields | None, attachments: list[Attachment], llm: StepLLM) -> TripPlan:
    plan = llm.run_json("extract", SYSTEM_PROMPT, _build_prompt(intake, attachments), TripPlan,
                        validate=validate_trip, max_tokens=16000)
    return dedupe_legs(plan)
