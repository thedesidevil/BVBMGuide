"""Batch B: important places hours/clinics/food venues, dishes, souvenirs, prose dedupe, contact queries, voice."""
from datetime import date, datetime, time

from src.aigv2 import hours
from src.aigv2.models import HotelStay, Place, WeeklyHours
from src.aigv2.planning.important_places import food_venue, important_places


def _wh(*periods):
    return WeeklyHours(periods={d: list(periods) for d in range(7)}, source="google")


def test_hours_use_am_pm_everywhere():
    assert hours.format_week(_wh((time(8), time(21)))) == "8:00 AM – 9:00 PM Mon–Sun"
    assert hours.format_week(_wh((time(7), time(22)))) == "7:00 AM – 10:00 PM Mon–Sun"
    assert hours.format_week(_wh((time(8), time(12)), (time(14), time(23, 30)))) == \
        "8:00 AM – 12:00 PM & 2:00 PM – 11:30 PM Mon–Sun"
    assert hours.format_week(_wh((time(0), hours.END_OF_DAY))) == "24 hours Mon–Sun"


def test_food_venues_are_not_groceries():
    assert food_venue("Warung Sampyan Mas")
    assert food_venue("Warung Made") and food_venue("Bali Coffee House") and not food_venue("ADI MART")


def mk(name, lat, note=None):
    return Place(query=name, place_id=name, name=name, address="", lat=lat, lng=0.0, status="OPERATIONAL",
                 hours=_wh((time(9), time(21))), phone="1", maps_url="u", fetched_at=datetime(2026, 1, 1), match_ok=True,
                 verify_note=note)


class FP:
    def __init__(self, hospital, clinics):
        self.hospital, self.clinics, self.calls = hospital, clinics, []

    def nearby(self, lat, lng, types, radius_m, max_results, city=None):
        self.calls.append(types)
        return {"hospital": self.hospital, "pharmacy": [], }.get(types[0], [mk("Warung Enak", 1.4), mk("Adi Mart", 1.5)])

    def nearby_peek(self, lat, lng, types, radius_m, max_results, city=None):
        return self.clinics if types == ["doctor", "medical_clinic"] else []


class FR:
    def __init__(self, drive):
        self.drive = drive

    def durations(self, origins, destinations, mode, when=None):
        t = self.drive if mode == "DRIVE" else {d: 4 for d in self.drive}
        return {(0, j): t.get(d[0]) for j, d in enumerate(destinations)}


def _run(fp, drive):
    st = HotelStay(city="X", hotel="H", check_in=date(2026, 9, 1), check_out=date(2026, 9, 3), source="voucher")
    return important_places([st], {"H": mk("H", 1.0)}, fp, FR(drive), ["taxi"])[0]


def test_clinic_replaces_a_far_hospital_from_the_cache_only():
    fp = FP([mk("Far Hospital", 1.6)], [mk("Nusa Medica Clinic", 1.7)])
    e = _run(fp, {1.6: 30, 1.7: 3, 1.4: 3, 1.5: 3})
    assert e.hospital.place.name == "Nusa Medica Clinic" and e.hospital.drive_min == 3
    assert any("clinic" in m.text for m in e.hospital.markers)
    assert ["doctor", "medical_clinic"] not in fp.calls  # peek only: no new Google call


def test_near_hospital_is_kept_and_food_venues_leave_the_grocery_column():
    fp = FP([mk("City Hospital", 1.6)], [mk("Nusa Medica Clinic", 1.7)])
    e = _run(fp, {1.6: 8, 1.7: 3, 1.4: 3, 1.5: 3})
    assert e.hospital.place.name == "City Hospital"
    assert [n.place.name for n in e.groceries] == ["Adi Mart"]
