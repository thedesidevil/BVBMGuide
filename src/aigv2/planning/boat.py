"""Boat/ferry facts the voucher states in words ("check in at 08:15 AM", "crossing takes 30 min").

Nothing here estimates a time: when the text does not say it, the value stays None.
"""
import re
from datetime import datetime
from typing import Optional

from src.aigv2.models import Booking, TransportLeg, TripPlan
from src.aigv2.planning.slots import parse_time

BOAT_BOOKING = re.compile(r"\b(fast[- ]?boat|ferry|speed ?boat)\b|\btransfer\b.*\bboat\b|\bboat\b.*\btransfer\b", re.I)
DEPARTS_AT = re.compile(r"(?:\bdepart\w*\b[^\n]*?\bat\s+|\bETD\s*:?\s*)(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\b)?)", re.I)
_TIME = r"(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\b)?)"
CHECK_IN_AT = re.compile(r"\bcheck[- ]?in\b[^\n]*?\b(?:at|by)\s+" + _TIME, re.I)
CROSSING_MIN = re.compile(r"\b(?:crossing|takes|journey)\b\s*(?:is\s+|takes\s+)?(?:about|approx\w*\.?|around)?\s*(\d{1,3})\s*(?:min\b|mins\b|minutes\b)(?!\s*[-–])", re.I)
BOAT_TYPE = re.compile(r"\b((?:shared|private)\s+(?:fast\s?boat|speed\s?boat|ferry))\b", re.I)


def parse_check_in(lines: list[str]) -> Optional[str]:
    """The boat check-in time text ("08:15 AM"); hotel check-in lines are ignored."""
    for line in lines:
        if re.search(r"\b(hotel|resort|villa)\b", line, re.I):
            continue
        m = CHECK_IN_AT.search(line)
        if m and parse_time(m.group(1)):
            return m.group(1)
    return None


def parse_crossing_min(lines: list[str]) -> Optional[int]:
    """Minutes when one number is stated ("crossing takes about 30 min"); a range like 30-45 is left unset."""
    for line in lines:
        m = CROSSING_MIN.search(line)
        if m:
            return int(m.group(1))
    return None


def parse_boat_type(lines: list[str]) -> Optional[str]:
    for line in lines:
        m = BOAT_TYPE.search(line)
        if m:
            t = m.group(1)
            return t[0].upper() + t[1:].lower()
    return None


def boat_bookings(trip: TripPlan, leg: TransportLeg) -> list[Booking]:
    """Boat bookings on the leg's day, best match first (a stated departure equal to the leg's wins)."""
    day = (leg.depart or leg.arrive).date() if (leg.depart or leg.arrive) else None
    found = [b for b in trip.bookings if b.day == day and BOAT_BOOKING.search(b.name)]

    def departs(b: Booking):
        for line in b.instructions:
            m = DEPARTS_AT.search(line)
            if m:
                return parse_time(m.group(1))
        return None

    return sorted(found, key=lambda b: departs(b) != (leg.depart.time() if leg.depart else None))


def enrich_boat_legs(trip: TripPlan) -> TripPlan:
    """Fill check_in / duration_min on boat legs from the matching booking's instructions when still empty."""
    legs = []
    for leg in trip.transport:
        if leg.kind == "boat" and (leg.depart or leg.arrive) and (leg.check_in is None or leg.duration_min is None):
            update = {}
            for b in boat_bookings(trip, leg)[:1]:
                if leg.check_in is None:
                    t = parse_time(parse_check_in(b.instructions))
                    if t:
                        update["check_in"] = datetime.combine(b.day, t)
                if leg.duration_min is None:
                    n = parse_crossing_min(b.instructions)
                    if n:
                        update["duration_min"] = n
            if update:
                leg = leg.model_copy(update=update)
        legs.append(leg)
    return trip.model_copy(update={"transport": legs})
