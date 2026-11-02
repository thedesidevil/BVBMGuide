from src.aigv2.google.routes import RoutesClient
from src.aigv2.models import Stop, TransitStep
from src.aigv2.planning.travel import (
    Leg, boat_leg, compute_legs, drive_day_legs, leg_markers, leg_options, rail_leg, rail_text,
)


class FakeResp:
    def __init__(self, payload=None, text=None):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    def __init__(self, *resps):
        self.resps = list(resps)
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers, json))
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]


def leg(walk=8, drive=5, transit=12, **kw):
    return Leg(from_name="A", to_name="B", walk_min=walk, drive_min=drive, transit_min=transit, **kw)


def test_walk_shown_only_when_short():
    assert leg_options(leg(8, 5), ["taxi"], 10) == [("Walk", 8), ("By car", 5)]
    assert leg_options(leg(25, 5), ["taxi"], 10) == [("By car", 5)]
    assert leg_options(leg(10, 5), ["taxi"], 10)[0] == ("Walk", 10)
    assert leg_options(leg(11, 5), ["taxi"], 10) == [("By car", 5)]


def test_transit_only_if_listed():
    assert ("By public transport", 12) not in leg_options(leg(25), ["taxi"], 10)
    assert leg_options(leg(25), ["taxi", "public_transport"], 10) == [("By car", 5), ("By public transport", 12)]


def test_private_driver_is_car():
    assert leg_options(leg(25), ["private_driver"], 10) == [("By car", 5)]
    assert leg_options(leg(25), ["self_drive"], 10) == [("By car", 5)]


def test_fallback_to_car_with_verify_marker():
    l = leg(25, 5)
    assert leg_options(l, ["public_transport"], 10) == [("By public transport", 12)]
    l2 = Leg(from_name="A", to_name="B", walk_min=25, drive_min=5, transit_min=None)
    assert leg_options(l2, ["public_transport"], 10) == [("By car", 5)]
    ms = leg_markers(l2, ["public_transport"], 10)
    assert [m.render() for m in ms] == ["⚠ VERIFY: travel mode for this leg"]
    assert leg_markers(leg(), ["taxi"], 10) == []


def test_no_route_at_all_is_flagged():
    l = Leg(from_name="A", to_name="B", walk_min=None, drive_min=None, transit_min=None)
    assert leg_options(l, ["taxi"], 10) == []
    assert len(leg_markers(l, ["taxi"], 10)) == 1


def test_matrix_parse():
    payload = [
        {"originIndex": 0, "destinationIndex": 0, "duration": "754s", "condition": "ROUTE_EXISTS"},
        {"originIndex": 0, "destinationIndex": 1, "condition": "ROUTE_NOT_FOUND"},
        {"originIndex": 1, "destinationIndex": 0, "duration": "60s", "condition": "ROUTE_EXISTS"},
    ]
    s = FakeSession(FakeResp(payload))
    rc = RoutesClient("KEY", session=s)
    out = rc.durations([(1.0, 2.0), (3.0, 4.0)], [(5.0, 6.0), (7.0, 8.0)], "WALK")
    assert out == {(0, 0): 13, (0, 1): None, (1, 0): 1, (1, 1): None}
    url, headers, body = s.posts[0]
    assert url == "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    assert "KEY" not in url and headers["X-Goog-Api-Key"] == "KEY"
    assert headers["X-Goog-FieldMask"] == "originIndex,destinationIndex,duration,condition"
    assert body["travelMode"] == "WALK"
    assert body["origins"][0] == {"waypoint": {"location": {"latLng": {"latitude": 1.0, "longitude": 2.0}}}}
    assert rc.calls["matrix_elements"] == 4


def test_matrix_parse_newline_delimited():
    text = (
        '{"originIndex":0,"destinationIndex":0,"duration":"600s","condition":"ROUTE_EXISTS"}\n'
        '{"originIndex":1,"destinationIndex":0,"condition":"ROUTE_NOT_FOUND"}\n'
    )
    rc = RoutesClient("K", session=FakeSession(FakeResp(text=text)))
    assert rc.durations([(0, 0), (1, 1)], [(2, 2)], "DRIVE") == {(0, 0): 10, (1, 0): None}


def test_transit_steps_parsed():
    payload = {"routes": [{"legs": [{"steps": [
        {"travelMode": "WALK"},
        {"travelMode": "TRANSIT", "transitDetails": {
            "stopDetails": {"departureStop": {"name": "Sultanahmet"}, "arrivalStop": {"name": "Kabatas"}},
            "headsign": "Kabatas",
            "transitLine": {"nameShort": "T1", "name": "Tram"},
            "stopCount": 6,
        }},
    ]}]}]}
    s = FakeSession(FakeResp(payload))
    rc = RoutesClient("K", session=s)
    steps = rc.transit_steps((1, 2), (3, 4))
    assert steps == [TransitStep(line="T1", headsign="Kabatas", board="Sultanahmet", alight="Kabatas", stops=6)]
    url, headers, body = s.posts[0]
    assert url == "https://routes.googleapis.com/directions/v2:computeRoutes"
    assert headers["X-Goog-FieldMask"] == "routes.legs.steps.transitDetails,routes.legs.steps.travelMode"
    assert body["travelMode"] == "TRANSIT"
    assert rc.calls["directions"] == 1


def test_transit_steps_no_route():
    rc = RoutesClient("K", session=FakeSession(FakeResp({})))
    assert rc.transit_steps((1, 2), (3, 4)) == []


class FakeRoutes:
    def __init__(self):
        self.modes = []

    def durations(self, o, d, mode, when=None):
        self.modes.append(mode)
        return {(0, 0): {"WALK": 25, "DRIVE": 6, "TRANSIT": None}[mode]}

    def transit_steps(self, o, d, when=None):
        raise AssertionError("no transit result, no steps")


def test_compute_legs_requests_only_needed_modes():
    r = FakeRoutes()
    pts = [("Hotel", (1.0, 1.0)), ("Museum", (2.0, 2.0)), ("Cafe", (3.0, 3.0))]
    legs = compute_legs(pts, r, ["taxi"])
    assert [(l.from_name, l.to_name, l.walk_min, l.drive_min, l.transit_min) for l in legs] == [
        ("Hotel", "Museum", 25, 6, None), ("Museum", "Cafe", 25, 6, None)]
    assert set(r.modes) == {"WALK", "DRIVE"}
    assert not any(l.no_route for l in legs)


def test_compute_legs_transit_steps():
    class R(FakeRoutes):
        def durations(self, o, d, mode, when=None):
            return {(0, 0): 9}

        def transit_steps(self, o, d, when=None):
            return [TransitStep(line="M2", headsign="X", board="A", alight="B", stops=3)]

    legs = compute_legs([("A", (1, 1)), ("B", (2, 2))], R(), ["public_transport"])
    assert legs[0].transit_min == 9 and legs[0].transit_steps[0].line == "M2"
    assert legs[0].drive_min == 9


def test_boat_leg_uses_voucher_time():
    l = boat_leg("Pier", "Island", 40)
    assert leg_options(l, ["taxi"], 10) == [("By boat", 40)]
    assert [m.render() for m in leg_markers(l, ["taxi"], 10)] == ["⚠ VERIFY: boat transfer timing"]


def test_unticketed_rail_is_duration_only():
    l = rail_leg("Rome", "Florence", 95, ticketed=False)
    assert rail_text(l) == "about 2 h by train"
    assert leg_options(l, ["taxi"], 10) == [("about 2 h by train", 120)]
    assert [m.render() for m in leg_markers(l, ["taxi"], 10)] == ["⚠ VERIFY: no ticket provided — check timetable"]
    assert leg_markers(rail_leg("Rome", "Florence", 95, ticketed=True), ["taxi"], 10) == []
    assert rail_text(rail_leg("A", "B", 180, ticketed=False)) == "about 3 h by train"


def test_rail_text_rounding_and_none():
    assert rail_text(rail_leg("A", "B", None, ticketed=False)) is None
    assert rail_text(rail_leg("A", "B", 10, ticketed=False)) == "about 10 min by train"
    assert rail_text(rail_leg("A", "B", 12, ticketed=False)) == "about 15 min by train"
    assert rail_text(rail_leg("A", "B", 75, ticketed=False)) == "about 1.5 h by train"
    nl = rail_leg("A", "B", None, ticketed=False)
    assert leg_options(nl, ["taxi"], 10) == []
    assert len(leg_markers(nl, ["taxi"], 10)) == 1


def test_walk_max_clamped_and_walk_none():
    assert leg_options(leg(15, 5), ["taxi"], 30) == [("By car", 5)]
    assert leg_options(leg(None, 5), ["taxi"], 10) == [("By car", 5)]


class MapRoutes:
    def __init__(self, table):
        self.table = table

    def durations(self, o, d, mode, when=None):
        return {(0, 0): self.table[mode]}

    def transit_steps(self, o, d, when=None):
        return []


def test_compute_legs_car_fallback_via_public_transport_only():
    legs = compute_legs([("A", (1, 1)), ("B", (2, 2))], MapRoutes({"WALK": 30, "DRIVE": 7, "TRANSIT": None}), ["public_transport"])
    assert legs[0].drive_min == 7 and not legs[0].no_route
    assert leg_options(legs[0], ["public_transport"], 10) == [("By car", 7)]
    assert [m.render() for m in leg_markers(legs[0], ["public_transport"], 10)] == ["⚠ VERIFY: travel mode for this leg"]


def test_compute_legs_route_not_found_flags_no_route():
    legs = compute_legs([("Pier", (1, 1)), ("Island", (2, 2))], MapRoutes({"WALK": None, "DRIVE": None, "TRANSIT": None}), ["taxi", "public_transport"])
    assert legs[0].no_route
    assert leg_options(legs[0], ["taxi"], 10) == []
    assert [m.render() for m in leg_markers(legs[0], ["taxi"], 10)] == [
        "⚠ VERIFY: no road route found — use the voucher's transfer time (boat/flight?)"]


def test_drive_day_legs_and_total():
    stops = [
        Stop(name="Viewpoint", minutes_from_prev=40, suggested_stop_min=20, km_from_prev=35.5),
        Stop(name="Village", minutes_from_prev=65, suggested_stop_min=60, km_from_prev=70.0),
    ]
    legs, total_min, total_km = drive_day_legs("Hotel", stops)
    assert [(l.from_name, l.to_name, l.drive_min, l.km) for l in legs] == [
        ("Hotel", "Viewpoint", 40, 35.5), ("Viewpoint", "Village", 65, 70.0)]
    assert (total_min, total_km) == (105, 105.5)


def test_transit_requests_carry_near_future_same_weekday_time():
    from datetime import datetime, timedelta, timezone
    s = FakeSession(FakeResp([{"originIndex": 0, "destinationIndex": 0, "duration": "600s"}]))
    rc = RoutesClient("K", session=s)
    rc.now = lambda: datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)  # a Thursday
    trip_time = datetime(2027, 3, 15, 12, 30)  # a Monday, naive local time
    rc.durations([(48.85, 2.35)], [(48.86, 2.34)], "TRANSIT", when=trip_time)
    assert s.posts[0][2]["departureTime"] == "2026-10-26T12:30:00+00:00"
    rc.durations([(48.85, 2.35)], [(48.86, 2.34)], "WALK", when=trip_time)
    assert "departureTime" not in s.posts[1][2]
    aware = trip_time.replace(tzinfo=timezone(timedelta(hours=1)))
    rc.durations([(48.85, 2.35)], [(48.86, 2.34)], "TRANSIT", when=aware)
    assert s.posts[2][2]["departureTime"] == "2026-10-26T12:30:00+01:00"
    rc.durations([(40.7, -74.0)], [(40.71, -74.0)], "TRANSIT", when=trip_time)
    assert s.posts[3][2]["departureTime"] == "2026-10-26T12:30:00-05:00"
    s2 = FakeSession(FakeResp({}))
    rc2 = RoutesClient("K", session=s2)
    rc2.now = rc.now
    rc2.transit_steps((48.85, 2.35), (48.86, 2.34), when=datetime(2027, 3, 18, 9, 0))  # a Thursday
    assert s2.posts[0][2]["departureTime"] == "2026-10-29T09:00:00+00:00"


def test_compute_legs_passes_leg_times_to_transit():
    from datetime import datetime

    class R(FakeRoutes):
        def __init__(self):
            super().__init__()
            self.whens = []

        def durations(self, o, d, mode, when=None):
            self.whens.append((mode, when))
            return {(0, 0): 9}

        def transit_steps(self, o, d, when=None):
            self.whens.append(("steps", when))
            return []

    r = R()
    t1, t2 = datetime(2027, 3, 15, 10), datetime(2027, 3, 15, 14)
    compute_legs([("A", (1, 1)), ("B", (2, 2)), ("C", (3, 3))], r, ["public_transport"], departures=[t1, t2])
    assert ("TRANSIT", t1) in r.whens and ("steps", t1) in r.whens and ("TRANSIT", t2) in r.whens
    assert ("WALK", None) in r.whens


# ---------- persistent route cache ----------

def _cached(tmp_path, *resps, days=30):
    from src.aigv2.store import RouteCache
    from src.library.ui.storage import LocalStorageBackend
    backend = LocalStorageBackend(tmp_path)
    s = FakeSession(*resps)
    return RoutesClient("K", session=s, cache=RouteCache(backend, days)), s, backend


def _ok(minutes_s="600s"):
    return FakeResp([{"originIndex": 0, "destinationIndex": 0, "duration": minutes_s, "condition": "ROUTE_EXISTS"}])


def test_route_cache_miss_then_hit_makes_no_call(tmp_path):
    rc, s, _ = _cached(tmp_path, _ok())
    assert rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE") == {(0, 0): 10}
    assert rc.calls["matrix_elements"] == 1 and len(s.posts) == 1
    assert rc.durations([(1.00001, 2.00001)], [(3.0, 4.0)], "DRIVE") == {(0, 0): 10}
    assert rc.calls["matrix_elements"] == 1 and len(s.posts) == 1


def test_route_cache_different_mode_or_coordinates_miss(tmp_path):
    rc, s, _ = _cached(tmp_path, _ok())
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE")
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "WALK")
    rc.durations([(1.001, 2.0)], [(3.0, 4.0)], "DRIVE")
    assert len(s.posts) == 3 and rc.calls["matrix_elements"] == 3


def test_route_cache_transit_buckets_weekday_and_hour(tmp_path):
    from datetime import datetime
    rc, s, _ = _cached(tmp_path, _ok())
    mon = datetime(2027, 3, 15, 12, 5)
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "TRANSIT", when=mon)
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "TRANSIT", when=datetime(2027, 3, 22, 12, 50))
    assert len(s.posts) == 1
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "TRANSIT", when=datetime(2027, 3, 15, 13, 0))
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "TRANSIT", when=datetime(2027, 3, 16, 12, 5))
    assert len(s.posts) == 3


def test_route_cache_ttl_expiry(tmp_path):
    import json
    rc, s, backend = _cached(tmp_path, _ok(), _ok("1200s"), days=30)
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE")
    key = next(k for k in backend.list_keys("cache/routes/"))
    raw = backend.read_json(key)
    raw["fetched_at"] = "2020-01-01T00:00:00+00:00"
    backend.write_json(key, raw)
    assert rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE") == {(0, 0): 20} and len(s.posts) == 2


def test_route_cache_does_not_store_failures(tmp_path):
    none = FakeResp([{"originIndex": 0, "destinationIndex": 0, "condition": "ROUTE_NOT_FOUND"}])
    rc, s, backend = _cached(tmp_path, none, _ok())
    assert rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE") == {(0, 0): None}
    assert list(backend.list_keys("cache/routes/")) == []
    assert rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE") == {(0, 0): 10} and len(s.posts) == 2

    class Boom(FakeResp):
        def raise_for_status(self):
            raise RuntimeError("500")
    rc2, _, backend2 = _cached(tmp_path / "b", Boom([]))
    try:
        rc2.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE")
    except RuntimeError:
        pass
    assert list(backend2.list_keys("cache/routes/")) == []


def test_route_cache_partial_matrix_only_fetches_missing_elements(tmp_path):
    rc, s, _ = _cached(tmp_path, _ok(), FakeResp([{"originIndex": 0, "destinationIndex": 0, "duration": "60s"}]))
    rc.durations([(1.0, 2.0)], [(3.0, 4.0)], "DRIVE")
    out = rc.durations([(1.0, 2.0), (5.0, 6.0)], [(3.0, 4.0)], "DRIVE")
    assert out == {(0, 0): 10, (1, 0): 1}
    assert rc.calls["matrix_elements"] == 2 and len(s.posts[1][2]["origins"]) == 1


def test_default_deps_routes_client_has_cache(monkeypatch, tmp_path):
    from src.aigv2 import pipeline
    from src.aigv2.store import RouteCache
    real = pipeline.load_settings
    monkeypatch.setattr(pipeline, "load_settings", lambda: real().model_copy(update={"data_root": tmp_path}))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    deps = pipeline.default_deps()
    assert isinstance(deps.routes.cache, RouteCache)
    assert deps.routes.cache.backend is deps.backend


class _NoRoad:
    def durations(self, origins, destinations, mode, when=None):
        return {(0, 0): None}

    def transit_steps(self, origin, destination, when=None):
        return []


def test_leg_without_a_road_route_gets_an_approximate_car_time():
    # about 2.2 km apart on an island: ceil(2.2 * 3 + 5) = 12
    legs = compute_legs([("Blue Lagoon", (-8.6800, 115.4500)), ("Devil's Tear", (-8.6800, 115.4700))], _NoRoad(), ["taxi"])
    assert legs[0].no_route is False and legs[0].approx_min == 12
    assert leg_options(legs[0], ["taxi"], 10) == [("By car (approx.)", 12)]
    assert leg_markers(legs[0], ["taxi"], 10) == []


def test_far_leg_without_a_road_route_stays_no_route():
    legs = compute_legs([("A", (-8.0, 115.0)), ("B", (-8.2, 115.2))], _NoRoad(), ["taxi"])
    assert legs[0].no_route is True and legs[0].approx_min is None


def test_meals_and_legs_share_the_estimate():
    from src.aigv2.planning.travel import approx_car_minutes
    assert approx_car_minutes(2.2) == 12 and approx_car_minutes(5.0) == 20 and approx_car_minutes(5.1) is None
