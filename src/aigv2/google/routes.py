import json
import math
from typing import Literal, Optional

import requests

from src.aigv2.planning.travel import TransitStep

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


class RoutesClient:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.calls: dict[str, int] = {"matrix_elements": 0, "directions": 0}

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
    ) -> dict[tuple[int, int], Optional[int]]:
        self.calls["matrix_elements"] += len(origins) * len(destinations)
        body = {
            "origins": [{"waypoint": _waypoint(o)} for o in origins],
            "destinations": [{"waypoint": _waypoint(d)} for d in destinations],
            "travelMode": mode,
        }
        out: dict[tuple[int, int], Optional[int]] = {
            (i, j): None for i in range(len(origins)) for j in range(len(destinations))
        }
        for el in _elements(self._post(MATRIX_URL, MATRIX_MASK, body)):
            if el.get("condition", "ROUTE_EXISTS") != "ROUTE_EXISTS" or not el.get("duration"):
                continue
            seconds = float(str(el["duration"]).rstrip("s"))
            out[(el.get("originIndex", 0), el.get("destinationIndex", 0))] = math.ceil(seconds / 60)
        return out

    def transit_steps(self, origin: tuple[float, float], destination: tuple[float, float]) -> list[TransitStep]:
        self.calls["directions"] += 1
        body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "TRANSIT"}
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
