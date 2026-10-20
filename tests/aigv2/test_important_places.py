from datetime import date, datetime, time

from src.aigv2.models import HotelStay, Place, WeeklyHours
from src.aigv2.planning.important_places import important_places


def hrs():
    return WeeklyHours(periods={d: [(time(9), time(21))] for d in range(6)}, source="google")


def mk(name, lat, hours="default", note=None):
    return Place(query=name, place_id=name, name=name, address="", lat=lat, lng=0.0, status="OPERATIONAL",
                 hours=hrs() if hours == "default" else hours, phone="+1 555 0100", maps_url="u",
                 fetched_at=datetime(2026, 1, 1), match_ok=True, verify_note=note)


def stay(hotel, city, d=1):
    return HotelStay(city=city, hotel=hotel, check_in=date(2026, 11, d), check_out=date(2026, 11, d + 2), source="voucher")


class FakePlaces:
    def __init__(self, by_origin):
        self.by_origin = by_origin
        self.calls = []

    def nearby(self, lat, lng, types, radius_m, max_results, city=None):
        self.calls.append((lat, types, radius_m, max_results, city))
        kind = "hospital" if types == ["hospital"] else "pharmacy" if types == ["pharmacy"] else "grocery"
        return self.by_origin[(lat, kind)]


class FakeRoutes:
    def __init__(self, walk, drive):
        self.walk, self.drive = walk, drive

    def durations(self, origins, destinations, mode):
        table = self.walk if mode == "WALK" else self.drive
        return {(0, j): table.get(d[0]) for j, d in enumerate(destinations)}


def test_two_hotels_two_cities_with_filtering_and_hospital():
    p1, p2, p3 = mk("Pharm A", 1.1), mk("Pharm B", 1.2), mk("Pharm Far", 1.3)
    g1, g2 = mk("Groc A", 1.4), mk("Groc B", 1.5)
    h_far, h_near = mk("Hosp Far", 1.6, note="check this hospital has 24-hour emergency care"), mk("Hosp Near", 1.7)
    q1 = mk("Pharm Q", 2.1)
    places = FakePlaces({
        (1.0, "pharmacy"): [p3, p1, p2], (1.0, "grocery"): [g1, g2], (1.0, "hospital"): [h_far, h_near],
        (2.0, "pharmacy"): [q1], (2.0, "grocery"): [], (2.0, "hospital"): [],
    })
    walk = {1.1: 4, 1.2: 9, 1.3: 14, 1.4: 6, 1.5: 3, 1.6: 30, 1.7: 40, 2.1: 5}
    drive = {1.6: 12, 1.7: 7}
    stays = [stay("Hotel One", "Istanbul"), stay("Hotel One", "istanbul", 3), stay("Hotel Two", "Rome", 5)]
    hotels = {"Hotel One": mk("Hotel One", 1.0), "Hotel Two": mk("Hotel Two", 2.0)}
    res = important_places(stays, hotels, places, FakeRoutes(walk, drive), ["taxi"])
    assert [(r.hotel, r.city) for r in res] == [("Hotel One", "Istanbul"), ("Hotel Two", "Rome")]
    one, two = res
    assert [n.place.name for n in one.pharmacies] == ["Pharm A", "Pharm B"]
    assert [n.walk_min for n in one.pharmacies] == [4, 9]
    assert [n.place.name for n in one.groceries] == ["Groc B", "Groc A"]
    assert one.markers == []
    assert one.hospital.place.name == "Hosp Near" and one.hospital.drive_min == 7
    assert places.calls[0] == (1.0, ["pharmacy"], 900, 6, "Istanbul")
    assert "Closed" in one.pharmacies[0].hours_text and one.pharmacies[0].place.phone == "+1 555 0100"
    assert [n.place.name for n in two.pharmacies] == ["Pharm Q"]
    texts = [m.text for m in two.markers]
    assert "fewer than 2 pharmacies within a 10-minute walk" in texts
    assert "fewer than 2 groceries within a 10-minute walk" in texts
    assert two.hospital is None


def test_pharmacy_beyond_ten_minutes_filtered_and_markers_carried():
    far = mk("Far", 1.1)
    near = mk("Near", 1.2, hours=None, note="Google coverage is limited here — verify details")
    places = FakePlaces({(1.0, "pharmacy"): [far, near], (1.0, "grocery"): [], (1.0, "hospital"): [mk("H", 1.5, note="nearest clinic, not a hospital")]})
    res = important_places([stay("H1", "Seoul")], {"H1": mk("H1", 1.0)}, places, FakeRoutes({1.1: 14, 1.2: 10, 1.5: 20}, {1.5: 5}), [])
    r = res[0]
    assert [n.place.name for n in r.pharmacies] == ["Near"]
    assert r.pharmacies[0].hours_text == "Hours unknown"
    assert r.pharmacies[0].markers[0].kind == "VERIFY"
    assert r.hospital.markers[0].text == "nearest clinic, not a hospital"
    assert any("fewer than 2 pharmacies" in m.text for m in r.markers)


def test_missing_hotel_place_gets_marker():
    res = important_places([stay("Ghost", "Rome")], {}, FakePlaces({}), FakeRoutes({}, {}), [])
    assert res[0].pharmacies == [] and res[0].markers[0].kind == "VERIFY"
