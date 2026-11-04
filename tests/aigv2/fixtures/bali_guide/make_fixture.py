"""One-off: slice the saved Bali run into guide_data.json (Days 1, 2, 4 and 5 only, client anonymised).

Usage: python3 tests/aigv2/fixtures/bali_guide/make_fixture.py <run_dir>
Read-only on the run folder. Mirrors src/aigv2/pipeline.py::_render_days / _render_qc.
"""
import json
import sys
from pathlib import Path

from src.aigv2.money import city_currency, price_text
from src.aigv2.pipeline import PlanState, _late_facts
from src.aigv2.planning.boat import enrich_boat_legs
from src.aigv2.render.document import GuideData, RenderDay
from src.aigv2.writing.days import DayText

KEEP = (1, 2, 4, 5)


class _NoFx:
    def rate(self, code, day):
        from src.aigv2.money import FxUnavailable
        raise FxUnavailable("offline fixture")


def main(run: Path) -> None:
    state = PlanState.model_validate(json.loads((run / "plan.json").read_text()))
    state.trip = enrich_boat_legs(state.trip)  # the saved trip predates check_in / duration_min
    days = []
    for ds in state.days:
        if ds.index not in KEEP:
            continue
        t = state.trip.transport
        picks = [p for p in state.picks if p.day_index == ds.index]
        cur = city_currency(ds.country, None) or ""
        prices = {c.lib["name"]: price_text(c.lib, cur, _NoFx(), ds.date) for p in picks for c in p.restaurants}
        days.append(RenderDay(
            index=ds.index, date=ds.date, city=ds.city,
            text=DayText.model_validate(json.loads((run / f"days/day_{ds.index:02d}.json").read_text())),
            result=ds.result, meals=picks, legs=ds.legs, places=ds.places, booking_by_item=ds.booking_by_item,
            arrival_booking=ds.arrival_booking, price_by_restaurant=prices,
            arrival=t[ds.arrival] if ds.arrival is not None else None,
            departure=t[ds.departure] if ds.departure is not None else None, prev_city=ds.prev_city,
            other_transport=[t[i] for i in ds.other_legs], utc_offset_hours=ds.utc_offset_hours,
            library_attractions=ds.library_attractions, **_late_facts(ds, state.trip)))
    trip = state.trip.model_copy(update={"days": [d for d in state.trip.days if d.date in {x.date for x in days}]})
    data = GuideData(trip=trip, title=json.loads((run / "sections/title.json").read_text())["title"], days=days,
                     sections={}, important=[], trip_scope=trip.trip_scope, modes=trip.travel_modes,
                     domestic=trip.trip_scope == "domestic")
    text = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=1)
    text = text.replace("Dilna Kallalthil", "Test Client One").replace("Dilna", "Test").replace("Apurva", "Test")
    out = Path(__file__).with_name("guide_data.json")
    out.write_text(text + "\n", encoding="utf-8")
    print(out, len(text))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
