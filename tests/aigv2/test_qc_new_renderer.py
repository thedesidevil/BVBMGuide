import copy
import io
import json
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

from src.aigv2.guide import model as M
from src.aigv2.guide.build import build_guide
from src.aigv2.llm import LLMStepError
from src.aigv2.models import WeeklyHours
from src.aigv2.qc import run_qc
from src.aigv2.qc.reader import read_docx
from src.aigv2.render.document import GuideData
from src.aigv2.render2.render import render_guide2
from tests.aigv2.test_pipeline import FakePlaces, FakeRoutes

_FIX = Path(__file__).parent / "fixtures" / "bali_guide" / "guide_data.json"


def _data():
    return GuideData.model_validate(json.loads(_FIX.read_text(encoding="utf-8")))


def _render(data):
    return render_guide2(build_guide(data, SimpleNamespace(walk_max_min=10)))


@pytest.fixture(scope="module")
def blob():
    return _render(_data())


@pytest.fixture(scope="module")
def model(blob):
    return read_docx(blob)


def _venues(model):
    return [v for d in model.days for s in d.slots for v in s.venues]


def test_every_day_has_index_and_date(model):
    assert [d.index for d in model.days] == [1, 2, 4, 5, 7, 8]
    assert model.days[0].header.startswith("Day 1 – Thu, 24 Sep | ")
    assert model.days[1].header.startswith("Day 2 – Fri, 25 Sep | ")


def test_every_meal_slot_has_venues_or_marker(model):
    meals = [s for d in model.days for s in d.slots if s.heading.split(" ")[0] in ("Lunch", "Dinner")]
    assert len(meals) >= 7
    for s in meals:
        assert s.venues or s.markers


def test_restaurant_venues_have_name_url_price_hours(model):
    lunch = next(s for s in model.days[1].slots if s.heading.startswith("Lunch"))
    assert [v.name for v in lunch.venues] == ["Queens of India", "Milk & Madu Ubud", "Natah Ubud"]
    for v in lunch.venues:
        assert v.url and v.url.startswith("https://")
        assert v.facts["PER PERSON"].startswith("₹") and v.facts["PRICE"] == v.facts["PER PERSON"]
        assert "–" in v.facts["OPENING HOURS"]
        assert v.facts["FROM HERE"].startswith(("Walk", "By car"))


def test_sightseeing_title_skips_eyebrow_and_reads_glance_facts(model):
    names = [v.name for s in model.days[1].slots for v in s.venues]
    assert "Tegallalang Rice Terrace (Viewpoint & Scenic Cafe)" in names
    v = next(v for v in _venues(model) if v.name.startswith("Tegallalang"))
    assert v.facts["GETTING THERE"] == "By car · 33 min"
    assert v.facts["OPENING HOURS"] == "8:00 AM – 6:00 PM"
    assert not any("◆" in n for n in names)


def test_hotel_and_booking_reference_facts(model):
    hotels = [v for v in _venues(model) if v.kind == "hotel"]
    assert hotels and all("CHECK-IN" in v.facts for v in hotels)
    transport = [v for v in _venues(model) if v.kind == "transport"]
    assert transport and all(v.facts.get("REFERENCE") for v in transport)


def test_placeholder_counts_one_marker():
    guide = build_guide(_data(), SimpleNamespace(walk_max_min=10))
    blocks = [c for p in guide.pages for c in p.components if isinstance(c, M.MealBlock) and c.restaurants]
    blocks[0].restaurants = []  # renders the dashed 3-row placeholder card
    blob = render_guide2(guide)
    doc = Document(io.BytesIO(blob))
    assert any("Placeholder Card" in t.style.name for t in doc.tables if t.style is not None)
    m = read_docx(blob)
    base = read_docx(render_guide2(build_guide(_data(), SimpleNamespace(walk_max_min=10))))
    n = lambda mm: sum(x.startswith("⚠ ADD RESTAURANT") for x in mm.markers)
    assert n(m) == n(base) + 1
    assert sum("ADD RESTAURANT" in p.text for p in m.paragraphs) == n(m)
    assert not any("Restaurant name (Maps link)" in p.text for p in m.paragraphs)


def test_review_markers_parse_without_staff_suffix(model):
    assert all("staff only" not in m for m in model.markers)
    assert "⚠ WRITE PERSONAL LETTER" in model.markers


# ---------- full QC on seeded problems ----------
class _LLM:
    cost_log: list = []

    def run_json(self, step, *a, **k):
        raise LLMStepError(step, ["offline"])


def _qc(blob, data, places=None):
    library = SimpleNamespace(restaurants=lambda city: [], coverage=lambda: {})
    out, result, _ = run_qc(blob, data.trip, {}, library, places or FakePlaces(), FakeRoutes(), _LLM(), [])
    return out, result


def _rules(result):
    return {f.rule for f in result.findings}


def test_clean_run_reads_days_and_markers(blob):
    _, result = _qc(blob, _data())
    assert "markers_remaining" in _rules(result)
    assert result.marker_count > 0
    assert "day_sequence" not in _rules(result)


def test_seeded_booking_missing():
    data = _data()
    b = copy.deepcopy(data.trip.bookings[0])
    b.name = "Sunset Dinner Cruise Zephyr"
    data.trip.bookings.append(b)
    _, result = _qc(_render(data), data)
    assert "booking_missing" in _rules(result)


def test_seeded_voice(blob):
    # the fixture's day prose says "We can ...": the voice check must see it in the new layout
    _, result = _qc(blob, _data())
    hits = [f for f in result.findings if f.rule == "voice_first_person"]
    assert hits and all(f.day for f in hits)


def test_seeded_not_open_at_slot():
    class ClosedPlaces(FakePlaces):
        def find(self, name, city, near=None, fresh=False):
            p = super().find(name, city, near, fresh)
            return p.model_copy(update={"hours": WeeklyHours(periods={d: [(time(2), time(3))] for d in range(7)},
                                                             source="google")})

    data = _data()
    _, result = _qc(_render(data), data, ClosedPlaces())
    assert "not_open_at_slot" in _rules(result)


def test_annotated_output_preserves_structure(blob):
    out, result = _qc(blob, _data())
    a, b = Document(io.BytesIO(blob)), Document(io.BytesIO(out))
    assert len(a.tables) == len(b.tables)
    assert len(a.sections) == len(b.sections)
    added = len(b.paragraphs) - len(a.paragraphs)
    assert 0 < added <= len(result.findings)
    assert any("Review Marker" in p.style.name or p.text.startswith("⚠") for p in b.paragraphs)


def test_annotation_lands_inside_the_right_day(blob):
    from src.aigv2.models import Finding
    from src.aigv2.qc.annotate import annotate
    out = annotate(blob, [Finding(rule="x", severity="error", message="SEEDED-NOTE", day=4)])
    texts = [p.text for p in Document(io.BytesIO(out)).paragraphs]
    i = next(i for i, t in enumerate(texts) if "SEEDED-NOTE" in t)
    assert [t for t in texts[:i] if t.startswith("◆ DAY ")][-1].startswith("◆ DAY 4 ")


def test_headings_and_title_for_new_layout(model):
    h1 = [t for lvl, t in model.headings if lvl == 1]
    assert "Day 1 – Thu, 24 Sep | Arrival in Bali" in h1
    assert model.title == "Ubud, Nusa Lembongan, Sanur Magic"


def test_pending_day_does_not_leak_over_other_text():
    from src.aigv2.qc.reader import _Reader
    assert _Reader.__init__ is not None  # structure pinned via the behaviour test below
    m = read_docx(_render(_data()))
    assert [d.index for d in m.days] == [1, 2, 4, 5, 7, 8]


def test_full_qc_has_no_title_or_section_order_noise(blob):
    _, result = _qc(blob, _data())
    noise = [f for f in result.findings if f.rule in ("title_destination", "section_order")]
    assert not [f for f in noise if "No day headers" in f.message or "No title" in f.message]
    assert not [f for f in noise if "out of order" in f.message or "before the last day" in f.message]


def test_marker_between_eyebrow_and_title_keeps_the_day(blob):
    from src.aigv2.models import Finding
    from src.aigv2.qc.annotate import annotate
    out = annotate(blob, [Finding(rule="x", severity="error", message="NOTE-ON-DAY", day=1)])
    m = read_docx(out)
    assert [d.index for d in m.days] == [1, 2, 4, 5, 7, 8]
    assert "Day 1 – Thu, 24 Sep | Arrival in Bali" in [t for lvl, t in m.headings if lvl == 1]


def test_reference_prose_titles_are_not_venues():
    from src.aigv2.writing.sections import SectionContent, SectionItem
    from src.aigv2.guide.build import build_reference_page
    from src.aigv2.writing.structured import Para
    data = _data()
    guide = build_guide(data, SimpleNamespace(walk_max_min=10))
    c = SectionContent(key="getting_around", items=[SectionItem(heading="x", body="y")],
                       transport=[Para(heading="Zebra Taxi Mode", body="Use the meter.")])
    guide.pages.insert(-1, build_reference_page("getting_around", c, data))
    m = read_docx(render_guide2(guide))
    assert "Zebra Taxi Mode" in m.text
    assert "Zebra Taxi Mode" not in {v.name for v in m.section_venues}
    assert not [v for v in m.section_venues if not v.url]


def test_at_your_hotel_parses_as_zero_walk():
    from src.aigv2.qc.facts import _guide_travel
    from src.aigv2.qc.reader import DocVenue
    v = DocVenue(name="x", url="", facts={"GETTING THERE": "At your hotel"}, body="", kind="venue")
    assert _guide_travel(v) == [("Walk", 0)]
