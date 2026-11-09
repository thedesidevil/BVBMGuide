"""Late-night arrivals: a landing before 05:00 the calendar day after a stay's first night belongs to that night's day."""
import re
from datetime import date, datetime, time, timedelta
from typing import Optional

from src.aigv2.models import Booking, TransportLeg, TripPlan

LATE_NIGHT_BEFORE_HOUR = 5
AIRPORT_PICKUP = re.compile(r"airport.*(pick-?up|transfer|meet)|(pick-?up|transfer|meet).*airport", re.I)


def is_late_night_landing(leg: TransportLeg, d: date) -> bool:
    """True when this leg lands after midnight on the day after `d` (the hotel night is `d`)."""
    return bool(leg.arrive and leg.arrive.date() == d + timedelta(days=1) and leg.arrive.hour < LATE_NIGHT_BEFORE_HOUR)


def pickup_before_landing(pickup_time: Optional[str], landing: datetime, d: date) -> Optional[str]:
    """The pick-up time as HH:MM when the driver is booked on day `d` earlier than the landing, else None."""
    from src.aigv2.planning.slots import parse_time
    t = parse_time(pickup_time)
    if t is None:
        return None
    start = datetime.combine(d + timedelta(days=1) if t.hour < LATE_NIGHT_BEFORE_HOUR else d, t)
    if start >= landing:
        return None
    return f"{t:%H:%M}"


def driver_time(booking: Booking) -> Optional[time]:
    """When the driver starts: a time in the booking's instructions ("Driver will come ... at 11:00 PM"), else its own time."""
    from src.aigv2.planning.slots import parse_time
    for line in (l for l in booking.instructions if re.search(r"driver|pick-?up", l, re.I)):
        t = parse_time(line)
        if t is not None:
            return t
    return parse_time(booking.time)


def late_night_days(trip: TripPlan) -> list[tuple[int, date, TransportLeg, Optional[Booking]]]:
    """(guide day number, date, landing leg, airport pick-up booking) for each late-night arrival day."""
    out = []
    for n, dp in enumerate(sorted(trip.days, key=lambda x: x.date), 1):
        if not any(s.check_in == dp.date for s in trip.hotels):
            continue
        legs = [l for l in trip.transport if is_late_night_landing(l, dp.date)]
        if not legs:
            continue
        leg = max(legs, key=lambda l: l.arrive)
        pick = next((b for b in trip.bookings if b.day == dp.date and AIRPORT_PICKUP.search(b.name)), None)
        out.append((n, dp.date, leg, pick))
    return out
