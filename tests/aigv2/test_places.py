import json

from src.aigv2.google.places import PlacesClient, weak_coverage
from src.aigv2.store import PlaceCache
from src.library.ui.storage import LocalStorageBackend


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers, json))
        return FakeResp(self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0])


def gp(name, addr="Beyoglu, Istanbul, Turkiye", pid="pid1", ptype="restaurant", lat=41.03, lng=28.97, **kw):
    d = {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": addr,
        "location": {"latitude": lat, "longitude": lng},
        "businessStatus": "OPERATIONAL",
        "websiteUri": "https://x.example",
        "internationalPhoneNumber": "+90 212 000 0000",
        "primaryType": ptype,
        "types": [ptype],
    }
    d.update(kw)
    return d


def client(tmp_path, *payloads):
    sess = FakeSession(*payloads)
    cache = PlaceCache(LocalStorageBackend(tmp_path), 30)
    return PlacesClient("KEY", cache, session=sess), sess


def test_find_parses_place(tmp_path):
    roh = {"periods": [{"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 17, "minute": 0}}]}
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant", regularOpeningHours=roh)]})
    p = c.find("Seher Restaurant", "Istanbul")
    assert p.match_ok and p.place_id == "pid1" and p.status == "OPERATIONAL"
    assert p.phone == "+90 212 000 0000" and p.website == "https://x.example"
    assert p.hours is not None and p.lat == 41.03
    assert "query_place_id=pid1" in p.maps_url and "utm_" not in p.maps_url
    assert "Seher+Restaurant+Istanbul" in p.maps_url
    url, headers, body = s.posts[0]
    assert url.endswith("places:searchText") and headers["X-Goog-Api-Key"] == "KEY"
    assert "places.primaryType" in headers["X-Goog-FieldMask"]
    assert body == {"textQuery": "Seher Restaurant, Istanbul", "languageCode": "en"}


def test_malformed_hours_become_none(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", regularOpeningHours={"periods": []})]})
    assert c.find("Seher Restaurant", "Istanbul").hours is None


def test_find_uses_cache(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.find("Seher Restaurant", "Istanbul")
    c.find("Seher Restaurant", "Istanbul")
    assert c.calls["text_search"] == 1 and len(s.posts) == 1
    c.find("Seher Restaurant", "Istanbul", fresh=True)
    assert c.calls["text_search"] == 2


def test_wrong_city_match_rejected(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Joe's Pizza", addr="1 Main St, Chicago, IL, USA")]})
    assert c.find("Joe's Pizza", "New York").match_ok is False


def test_chain_name_mismatch_rejected(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Kuaför")]})
    assert c.find("Seher Restaurant", "Istanbul").match_ok is False


def test_near_allows_address_without_city(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Some Street 5")]})
    p = c.find("Seher Restaurant", "Istanbul", near=(41.03, 28.98))
    assert p.match_ok
    assert s.posts[0][2]["locationBias"]["circle"]["radius"] == 20000.0


def test_no_results_returns_none(tmp_path):
    c, _ = client(tmp_path, {})
    assert c.find("Nothing", "Istanbul") is None


def test_picks_matching_candidate(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Kuaför", pid="a"), gp("Seher Restaurant", pid="b")]})
    p = c.find("Seher Restaurant", "Istanbul")
    assert p.place_id == "b" and p.match_ok


def test_nearby_request_body(tmp_path):
    c, s = client(tmp_path, {"places": [gp("City Pharmacy", ptype="pharmacy")]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5)
    url, _, body = s.posts[0]
    assert url.endswith("places:searchNearby")
    assert body["includedTypes"] == ["pharmacy"] and body["maxResultCount"] == 5
    assert body["locationRestriction"]["circle"] == {"center": {"latitude": 41.0, "longitude": 29.0}, "radius": 1500.0}
    assert c.calls["nearby"] == 1 and len(out) == 1 and out[0].match_ok


def test_steroid_shop_not_pharmacy(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Anabolic Sports Cosmetic Shop", ptype="store", pid="a"),
        gp("Eczane Sports Pharmacy", ptype="pharmacy", pid="b"),
        gp("Merkez Eczanesi", ptype="pharmacy", pid="c"),
    ]})
    out = c.nearby(41.0, 29.0, ["pharmacy"], 1500, 5)
    assert [p.place_id for p in out] == ["c"]


def test_equipment_firm_not_hospital(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Medical Equipment B.V.", ptype="hospital", pid="a"),
        gp("Dental Hospital", ptype="hospital", pid="b"),
        gp("General Hospital", ptype="hospital", pid="c", lat=41.001, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert [p.place_id for p in out] == ["c"]


def test_hospital_prefers_emergency(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Town Hospital", ptype="hospital", pid="a", lat=41.001, lng=29.0),
        gp("City Emergency Hospital", ptype="hospital", pid="b", lat=41.005, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert out[0].place_id == "b"


def test_hospital_falls_back_to_clinic(tmp_path):
    far = gp("Far Hospital", ptype="hospital", pid="far", lat=41.5, lng=29.0)
    clinic = gp("Island Clinic", ptype="medical_clinic", pid="cl", lat=41.001, lng=29.0)
    c, s = client(tmp_path, {"places": [far]}, {"places": [clinic]})
    out = c.nearby(41.0, 29.0, ["hospital"], 20000, 3)
    assert [p.place_id for p in out] == ["cl"]
    assert s.posts[1][2]["includedTypes"] == ["doctor", "medical_clinic"]
    assert out[0].verify_note == "nearest clinic, not a hospital"
    assert c.calls["nearby"] == 2


def test_weak_coverage():
    assert weak_coverage("Seoul, South Korea") and weak_coverage("South Korea") and weak_coverage("Seoul") and weak_coverage("China")
    assert not weak_coverage("Istanbul")


def _roh(open_h, close_h):
    return {"periods": [
        {"open": {"day": d, "hour": open_h, "minute": 0}, "close": {"day": d, "hour": close_h, "minute": 0}}
        for d in range(7)
    ]}


def test_city_match_is_word_bounded(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Via Roma 1, Venice, Italy")]})
    assert c.find("Seher Restaurant", "Nice").match_ok is False
    c2, _ = client(tmp_path / "b", {"places": [gp("Joe's Pizza", addr="1 Broadway, New York, NY 10001")]})
    assert c2.find("Joe's Pizza", "New York").match_ok is True


def test_weak_coverage_note_on_find_and_nearby(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Seher Restaurant", addr="Gangnam, Seoul, South Korea")]})
    assert c.find("Seher Restaurant", "Seoul").verify_note == "Google coverage is limited here — verify details"
    c2, _ = client(tmp_path / "b", {"places": [gp("Merkez Pharmacy", ptype="pharmacy")]})
    out = c2.nearby(37.5, 127.0, ["pharmacy"], 1000, 3, city="Seoul, South Korea")
    assert out[0].verify_note == "Google coverage is limited here — verify details"
    c3, _ = client(tmp_path / "c", {"places": [gp("Seher Restaurant")]})
    assert c3.find("Seher Restaurant", "Istanbul").verify_note is None


def test_hospital_unknown_hours_note(tmp_path):
    c, _ = client(tmp_path, {"places": [gp("Town Hospital", ptype="hospital", lat=41.001, lng=29.0)]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 3)
    assert out[0].verify_note == "check this hospital has 24-hour emergency care"


def test_hospital_24h_filter(tmp_path):
    c, _ = client(tmp_path, {"places": [
        gp("Day Hospital", ptype="hospital", pid="a", lat=41.001, lng=29.0, regularOpeningHours=_roh(9, 17)),
        gp("Round Clock Hospital", ptype="hospital", pid="b", lat=41.002, lng=29.0,
           regularOpeningHours={"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital"], 5000, 5)
    assert [p.place_id for p in out] == ["b"]


def test_filter_only_for_hospital_results(tmp_path):
    c, s = client(tmp_path, {"places": [
        gp("Day Pharmacy", ptype="pharmacy", pid="p", regularOpeningHours=_roh(9, 17)),
        gp("City Emergency Hospital", ptype="hospital", pid="h", lat=41.001, lng=29.0),
    ]})
    out = c.nearby(41.0, 29.0, ["hospital", "pharmacy"], 5000, 5)
    assert {p.place_id for p in out} == {"p", "h"}
    assert s.posts[0][2]["languageCode"] == "en"


def test_search_text_language_code(tmp_path):
    c, s = client(tmp_path, {"places": [gp("Seher Restaurant")]})
    c.find("Seher Restaurant", "Istanbul")
    assert s.posts[0][2]["languageCode"] == "en"
