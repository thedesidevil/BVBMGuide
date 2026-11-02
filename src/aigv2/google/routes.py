import json
import math
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import requests

from src.aigv2.models import TransitStep

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
DIRECTIONS_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_MASK = "originIndex,destinationIndex,duration,condition"
STEPS_MASK = "routes.legs.steps.transitDetails,routes.legs.steps.travelMode"


def _waypoint(p: tuple[float, float]) -> dict:
    return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}


def _elements(resp: requests.Response) -> list[dict]:
    try:
        data = resp.json()
    except ValueError:
        data = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    return data if isinstance(data, list) else [data]


def departure_time(when: datetime, lng: float, now: datetime) -> str:
    """Transit timetables only exist for the near future: same weekday and local time, within the next week."""
    tz = when.tzinfo or timezone(timedelta(hours=round(lng / 15)))
    base = now.astimezone(tz).date() + timedelta(days=1)
    day = base + timedelta(days=(when.weekday() - base.weekday()) % 7)
    return datetime.combine(day, when.time().replace(tzinfo=None), tzinfo=tz).isoformat()


class RoutesClient:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None, cache=None):
        self.api_key = api_key
        self.cache = cache
        self.session = session or requests.Session()
        self.calls: dict[str, int] = {"matrix_elements": 0, "directions": 0}
        self.now = lambda: datetime.now(timezone.utc)

    def _post(self, url: str, mask: str, body: dict) -> requests.Response:
        resp = self.session.post(
            url,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": mask, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    def durations(
        self,
        origins: list[tuple[float, float]],
        destinations: list[tuple[float, float]],
        mode: Literal["WALK", "DRIVE", "TRANSIT"],
        when: Optional[datetime] = None,
    ) -> dict[tuple[int, int], Optional[int]]:
        out: dict[tuple[int, int], Optional[int]] = {
            (i, j): None for i in range(len(origins)) for j in range(len(destinations))
        }
        keys = {pair: self._cache_key(origins[pair[0]], destinations[pair[1]], mode, when) for pair in out}
        missing = []
        for pair, key in keys.items():
            hit = self.cache.get(key) if self.cache else None
            if hit is None:
                missing.append(pair)
            else:
                out[pair] = hit
        if not missing:
            return out
        oi = sorted({i for i, _ in missing})
        dj = sorted({j for _, j in missing})
        sub_o, sub_d = [origins[i] for i in oi], [destinations[j] for j in dj]
        self.calls["matrix_elements"] += len(sub_o) * len(sub_d)
        body = {
            "origins": [{"waypoint": _waypoint(o)} for o in sub_o],
            "destinations": [{"waypoint": _waypoint(d)} for d in sub_d],
            "travelMode": mode,
        }
        if mode == "TRANSIT" and when is not None and sub_o:
            body["departureTime"] = departure_time(when, sub_o[0][1], self.now())
        for el in _elements(self._post(MATRIX_URL, MATRIX_MASK, body)):
            if el.get("condition", "ROUTE_EXISTS") != "ROUTE_EXISTS" or not el.get("duration"):
                continue
            seconds = float(str(el["duration"]).rstrip("s"))
            try:
                pair = (oi[el.get("originIndex", 0)], dj[el.get("destinationIndex", 0)])
            except IndexError:
                continue
            out[pair] = math.ceil(seconds / 60)
            if self.cache:
                self.cache.put(keys[pair], out[pair])
        return out

    @staticmethod
    def _cache_key(o: tuple[float, float], d: tuple[float, float], mode: str, when: Optional[datetime]) -> str:
        slot = f"{when.weekday()}-{when.hour}" if mode == "TRANSIT" and when is not None else "-"
        return f"{o[0]:.4f},{o[1]:.4f}|{d[0]:.4f},{d[1]:.4f}|{mode}|{slot}"

    def transit_steps(self, origin: tuple[float, float], destination: tuple[float, float],
                      when: Optional[datetime] = None) -> list[TransitStep]:
        self.calls["directions"] += 1
        body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "TRANSIT"}
        if when is not None:
            body["departureTime"] = departure_time(when, origin[1], self.now())
        data = self._post(DIRECTIONS_URL, STEPS_MASK, body).json()
        routes = data.get("routes") or []
        if not routes:
            return []
        steps = []
        for leg in routes[0].get("legs", []):
            for s in leg.get("steps", []):
                td = s.get("transitDetails")
                if s.get("travelMode") != "TRANSIT" or not td:
                    continue
                line = td.get("transitLine", {})
                stops = td.get("stopDetails", {})
                steps.append(TransitStep(
                    line=line.get("nameShort") or line.get("name") or "",
                    headsign=td.get("headsign", ""),
                    board=stops.get("departureStop", {}).get("name", ""),
                    alight=stops.get("arrivalStop", {}).get("name", ""),
                    stops=int(td.get("stopCount", 0)),
                ))
        return steps
