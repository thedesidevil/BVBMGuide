from datetime import date, time

from src.aigv2.models import Booking
from src.aigv2.planning.late_night import driver_time


def _b(time_=None, instr=()):
    return Booking(name="Airport pick-up", day=date(2026, 9, 24), time=time_, source="voucher", instructions=list(instr))


def test_driver_time_from_instructions():
    b = _b("00:10", ["MIDNIGHT ARRIVAL AT 00:10 ON 25 SEPTEMBER", "Driver will come to the airport at 11:00 PM."])
    assert driver_time(b) == time(23, 0)


def test_driver_time_falls_back_to_booking_time():
    assert driver_time(_b("23:00")) == time(23, 0)


def test_driver_time_none():
    assert driver_time(_b(None, ["Driver will wait."])) is None
