from datetime import datetime

from src.aigv2.guide import model as m
from src.aigv2.guide.build import build_guide, build_important_page, build_reference_page
from src.aigv2.models import Marker, Place
from src.aigv2.planning.important_places import ImportantPlaces, NearbyPlace
from src.aigv2.writing.sections import SectionContent, SectionItem
from tests.aigv2.test_guide_build import SETTINGS, load


def _place(name: str, url: str, phone: str | None = None) -> Place:
    return Place(query=name, place_id=name, name=name, address="1 Dummy St", lat=0.0, lng=0.0,
                 status="OPERATIONAL", maps_url=url, fetched_at=datetime(2026, 1, 1), match_ok=True, phone=phone)


def _near(name: str, walk=3, drive=None, hours="Mon–Sun 08:00–22:00", markers=()) -> NearbyPlace:
    return NearbyPlace(place=_place(name, f"https://maps.example/{name}"), walk_min=walk, drive_min=drive,
                       hours_text=hours, markers=list(markers))


def _sec(key: str, **kw) -> SectionContent:
    kw.setdefault("items", [SectionItem(heading=f"{key} A", body=f"{key} body", verify=False)])
    return SectionContent(key=key, **kw)


def _data(sections=None, important=None):
    d = load()
    d.sections = sections or {}
    d.important = important or []
    return d


def test_every_present_section_has_a_page():
    data = _data({"safety": _sec("safety"), "packing": _sec("packing"), "health": _sec("health"),
                  "money": _sec("money"), "connectivity": None})
    pages = [p for p in build_guide(data, SETTINGS).pages if p.kind == "reference"]
    assert [p.bookmark for p in pages] == ["sec_packing", "sec_money", "sec_health", "sec_safety"]
    assert pages[0].title == "Tailored Packing List"
    opener, paras = pages[0].components[:2]
    assert opener.type == "ReferenceOpener" and opener.eyebrow == "BEFORE YOU GO" and opener.title == pages[0].title
    assert paras.items[0] == m.TitledPara(heading="packing A", body="packing body")
    assert pages[-1].components[0].eyebrow == "WHILE YOU'RE THERE"
    assert [p.kind for p in build_guide(data, SETTINGS).pages][-1] == "thank_you"


def test_important_places_groups_per_hotel():
    e1 = ImportantPlaces(city="Ubud", hotel="Hotel One", pharmacies=[_near("P1"), _near("P2", walk=5, drive=2)],
                         groceries=[_near("G1")], hospital=_near("H1", walk=None, drive=12))
    e2 = ImportantPlaces(city="Seminyak", hotel="Hotel Two", pharmacies=[_near("P3")])
    page = build_important_page([e1, e2])
    assert page.title == "Important Places Around Your Stays" and page.bookmark == "sec_important"
    groups = page.components[1]
    assert groups.type == "PlaceGroups" and len(groups.hotels) == 2
    h1, h2 = groups.hotels
    assert (len(h1.pharmacies), len(h1.groceries), len(h1.hospitals)) == (2, 1, 1)
    assert (len(h2.pharmacies), len(h2.groceries), len(h2.hospitals)) == (1, 0, 0)
    assert h1.pharmacies[1].name == m.Link(text="P2", url="https://maps.example/P2")
    assert (h1.pharmacies[1].walk_min, h1.pharmacies[1].drive_min) == (5, 2)
    assert h1.pharmacies[0].hours_text == "Mon–Sun 08:00–22:00"
    assert (h1.hospitals[0].walk_min, h1.hospitals[0].drive_min) == (None, 12)
    assert h1.hotel.text == "Hotel One" and h1.hotel.url.startswith("https://www.google.com/maps")
    assert h1.city == "Ubud" and h1.dates == ""


def test_important_dates_from_matching_stay():
    data = _data()
    stay = data.trip.hotels[0]
    page = build_important_page([ImportantPlaces(city=stay.city, hotel=stay.hotel)], data)
    h = page.components[1].hotels[0]
    assert h.dates and f"{stay.check_in.day}" in h.dates and f"{stay.check_out.day}" in h.dates
    assert "–" in h.dates


def test_markers_carried_as_markerrefs():
    c = _sec("money", items=[SectionItem(heading="Cash", body="b", verify=True),
                             SectionItem(heading="Cards", body="b", verify=False)],
             markers=[Marker(kind="CHECK", text="section note")])
    page = build_reference_page("money", c, _data())
    block = page.components[-1]
    assert block.type == "ReviewMarkerBlock"
    assert block.markers == [m.MarkerRef(kind="VERIFY", text="Cash"), m.MarkerRef(kind="CHECK", text="section note")]
    near = _near("P1", markers=[Marker(kind="VERIFY", text="hours unknown")])
    h = build_important_page([ImportantPlaces(city="X", hotel="H", pharmacies=[near],
                                              markers=[Marker(kind="VERIFY", text="fewer")])]).components[1].hotels[0]
    assert h.pharmacies[0].markers == [m.MarkerRef(kind="VERIFY", text="hours unknown")]
    assert h.markers == [m.MarkerRef(kind="VERIFY", text="fewer")]


def test_by_country_headings_only_when_multiple_countries():
    one = _sec("etiquette", items=[], by_country={"Indonesia": [SectionItem(heading="a", body="b", verify=False)]})
    comps = build_reference_page("etiquette", one, _data()).components
    assert [c.items[0].heading for c in comps if c.type == "TitledParas"] == ["a"]
    two = _sec("etiquette", items=[], by_country={"Indonesia": [SectionItem(heading="a", body="b", verify=False)],
                                                  "": [SectionItem(heading="c", body="d", verify=False)]})
    paras = [c for c in build_reference_page("etiquette", two, _data()).components if c.type == "TitledParas"]
    assert [[i.heading for i in p.items] for p in paras] == [["Indonesia", "a"], ["General", "c"]]


def test_important_places_no_hospital_has_empty_list():
    h = build_important_page([ImportantPlaces(city="X", hotel="H")]).components[1].hotels[0]
    assert h.hospitals == [] and h.pharmacies == [] and h.groceries == [] and h.dates == ""
    assert h.hotel.text == "H" and h.hotel.url


def test_empty_important_list_gives_no_important_page():
    assert build_important_page([]) is None
    pages = build_guide(_data({"packing": _sec("packing")}), SETTINGS).pages
    assert "sec_important" not in [p.bookmark for p in pages]


def _stay(hotel, city, a, b):
    from src.aigv2.models import HotelStay
    return HotelStay(city=city, hotel=hotel, check_in=a, check_out=b, source="voucher")


def test_same_hotel_twice_gets_own_stay_dates():
    from datetime import date
    data = _data()
    data.trip.hotels = [_stay("Hotel Z", "Ubud", date(2026, 10, 5), date(2026, 10, 7)),
                        _stay("Hotel Z", "Ubud", date(2026, 9, 28), date(2026, 10, 2))]
    es = [ImportantPlaces(city="Ubud", hotel="Hotel Z"), ImportantPlaces(city="Ubud", hotel="Hotel Z")]
    hs = build_important_page(es, data).components[1].hotels
    assert [h.dates for h in hs] == ["28 September – 2 October", "5 – 7 October"]


def test_cross_year_span_and_city_fallback():
    from datetime import date
    data = _data()
    data.trip.hotels = [_stay("Hotel Y", "Old Name", date(2026, 12, 30), date(2027, 1, 3))]
    h = build_important_page([ImportantPlaces(city="New Name", hotel="Hotel Y")], data).components[1].hotels[0]
    assert h.dates == "30 December 2026 – 3 January 2027"


def test_unmatched_hotel_place_falls_back_to_search_url():
    data = _data()
    stay = data.trip.hotels[0]
    day = data.days[0]
    pl = _place(stay.hotel, "https://maps.example/bad").model_copy(update={"match_ok": False})
    day.places[stay.hotel] = pl
    h = build_important_page([ImportantPlaces(city=stay.city, hotel=stay.hotel)], data).components[1].hotels[0]
    assert h.hotel.url.startswith("https://www.google.com/maps/search")


def test_missing_travel_time_gets_marker():
    n = _near("P9", walk=None, drive=None)
    h = build_important_page([ImportantPlaces(city="X", hotel="H", pharmacies=[n])]).components[1].hotels[0]
    assert m.MarkerRef(kind="VERIFY", text="P9: travel time from the hotel") in h.pharmacies[0].markers


def test_markers_only_section_has_no_empty_paras():
    c = SectionContent(key="health", items=[], markers=[Marker(kind="CHECK", text="n")])
    comps = build_reference_page("health", c, _data()).components
    assert [x.type for x in comps] == ["ReferenceOpener", "ReviewMarkerBlock"]


def test_by_country_verify_items_become_markers():
    c = _sec("etiquette", items=[], by_country={"A": [SectionItem(heading="Tipping", body="b", verify=True)]})
    block = build_reference_page("etiquette", c, _data()).components[-1]
    assert block.markers == [m.MarkerRef(kind="VERIFY", text="Tipping")]
