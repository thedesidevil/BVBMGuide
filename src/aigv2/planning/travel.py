import math
from typing import Optional, Protocol

from pydantic import BaseModel, Field

from src.aigv2.models import Marker, Stop, TransitStep

_CAR_MODES = {"taxi", "self_drive", "private_driver"}


class Leg(BaseModel):
    from_name: str
    to_name: str
    walk_min: Optional[int] = None
    drive_min: Optional[int] = None
    transit_min: Optional[int] = None
    transit_steps: list[TransitStep] = Field(default_factory=list)
    kind: str = ""
    km: Optional[float] = None
    ticketed: bool = True
    no_route: bool = False


class _Routes(Protocol):
    def durations(self, origins, destinations, mode) -> dict: ...
    def transit_steps(self, origin, destination) -> list[TransitStep]: ...


def boat_leg(from_name: str, to_name: str, minutes: int) -> Leg:
    return Leg(from_name=from_name, to_name=to_name, drive_min=minutes, kind="boat")


def rail_leg(from_name: str, to_name: str, minutes: Optional[int], ticketed: bool) -> Leg:
    return Leg(from_name=from_name, to_name=to_name, transit_min=minutes, kind="rail", ticketed=ticketed)


def _rail_rounded(leg: Leg) -> Optional[int]:
    m = leg.transit_min
    if m is None:
        return None
    return math.ceil(max(m, 1) / 5) * 5 if m < 60 else math.ceil(m / 30) * 30


def rail_text(leg: Leg) -> Optional[str]:
    m = _rail_rounded(leg)
    if m is None:
        return None
    return f"about {m} min by train" if m < 60 else f"about {m / 60:g} h by train"


def leg_options(leg: Leg, modes: list[str], walk_max: int) -> list[tuple[str, int]]:
    walk_max = min(walk_max, 10)
    if leg.no_route:
        return []
    if leg.kind == "boat":
        return [("By boat", leg.drive_min)] if leg.drive_min is not None else []
    if leg.kind == "rail":
        if leg.transit_min is None:
            return []
        if not leg.ticketed:
            return [(rail_text(leg), _rail_rounded(leg))]
        return [("By train", leg.transit_min)]
    opts: list[tuple[str, int]] = []
    if leg.walk_min is not None and leg.walk_min <= walk_max:
        opts.append(("Walk", leg.walk_min))
    if _CAR_MODES & set(modes) and leg.drive_min is not None:
        opts.append(("By car", leg.drive_min))
    if "public_transport" in modes and leg.transit_min is not None:
        opts.append(("By public transport", leg.transit_min))
    if not opts and leg.drive_min is not None:
        opts.append(("By car", leg.drive_min))
    return opts


def leg_markers(leg: Leg, modes: list[str], walk_max: int) -> list[Marker]:
    walk_max = min(walk_max, 10)
    if leg.no_route:
        return [Marker(kind="VERIFY", text="no road route found — use the voucher's transfer time (boat/flight?)")]
    if leg.kind == "boat":
        return [Marker(kind="VERIFY", text="boat transfer timing")]
    if leg.kind == "rail":
        return [] if leg.ticketed else [Marker(kind="VERIFY", text="no ticket provided — check timetable")]
    walk_ok = leg.walk_min is not None and leg.walk_min <= walk_max
    allowed = (
        (_CAR_MODES & set(modes) and leg.drive_min is not None)
        or ("public_transport" in modes and leg.transit_min is not None)
    )
    if not walk_ok and not allowed:
        return [Marker(kind="VERIFY", text="travel mode for this leg")]
    return []


def compute_legs(points: list[tuple[str, tuple[float, float]]], routes: _Routes, modes: list[str], walk_max: int = 10) -> list[Leg]:
    legs = []
    for (n1, p1), (n2, p2) in zip(points, points[1:]):
        def minutes(mode: str) -> Optional[int]:
            return routes.durations([p1], [p2], mode)[(0, 0)]

        leg = Leg(from_name=n1, to_name=n2, walk_min=minutes("WALK"))
        leg.drive_min = minutes("DRIVE")
        if "public_transport" in modes:
            leg.transit_min = minutes("TRANSIT")
            if leg.transit_min is not None:
                leg.transit_steps = routes.transit_steps(p1, p2)
        leg.no_route = (
            leg.drive_min is None
            and leg.transit_min is None
            and (leg.walk_min is None or leg.walk_min > min(walk_max, 10))
        )
        legs.append(leg)
    return legs


def drive_day_legs(origin_name: str, stops: list[Stop]) -> tuple[list[Leg], int, float]:
    legs = []
    prev = origin_name
    for s in stops:
        legs.append(Leg(from_name=prev, to_name=s.name, drive_min=s.minutes_from_prev, km=s.km_from_prev, kind="drive"))
        prev = s.name
    return legs, sum(s.minutes_from_prev for s in stops), round(sum(s.km_from_prev for s in stops), 1)
