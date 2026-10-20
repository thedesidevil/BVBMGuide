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

    def durations(self, o, d, mode):
        self.modes.append(mode)
        return {(0, 0): {"WALK": 25, "DRIVE": 6, "TRANSIT": None}[mode]}

    def transit_steps(self, o, d):
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
        def durations(self, o, d, mode):
            return {(0, 0): 9}

        def transit_steps(self, o, d):
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

    def durations(self, o, d, mode):
        return {(0, 0): self.table[mode]}

    def transit_steps(self, o, d):
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
