from datetime import date, time

import pytest

from src.aigv2 import hours
from src.aigv2.models import WeeklyHours

MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
FRI = date(2026, 10, 30)
SAT = date(2026, 10, 31)
SUN = date(2026, 11, 1)


def _g(day, h, m=0):
    return {"day": day, "hour": h, "minute": m}


def test_google_periods_parse_and_overnight_split():
    roh = {"periods": [
        {"open": _g(5, 18), "close": _g(6, 2)},
        {"open": _g(1, 9), "close": _g(1, 17, 30)},
    ]}
    wh = hours.from_google(roh)
    assert isinstance(wh, WeeklyHours) and wh.source == "google"
    assert wh.periods[0] == [(time(9), time(17, 30))]
    assert wh.periods[4] == [(time(18), time(23, 59, 59))]
    assert wh.periods[5] == [(time(0), time(2))]
    assert hours.is_open_for(wh, FRI, time(23, 0), 90) is True
    assert hours.is_open_for(wh, FRI, time(23, 0), 200) is False
    assert hours.is_open_for(wh, SAT, time(1, 0), 60) is True


def test_google_24_hours():
    wh = hours.from_google({"periods": [{"open": _g(0, 0)}]})
    assert all(d in wh.periods for d in range(7))
    assert hours.is_open_for(wh, SUN, time(3), 60) is True
    assert hours.format_for_day(wh, SUN) == "Open 24 hours"


def test_google_missing_periods_raises():
    with pytest.raises(ValueError):
        hours.from_google({"weekdayDescriptions": ["x"]})


def test_closed_on_monday():
    roh = {"periods": [{"open": _g(d, 10), "close": _g(d, 22)} for d in (2, 3, 4, 5, 6, 0)]}
    wh = hours.from_google(roh)
    assert hours.is_open_for(wh, MON, time(12), 60) is False
    assert hours.format_for_day(wh, MON) == "Closed"
    assert hours.format_for_day(wh, TUE) == "10:00 AM – 10:00 PM"


def test_lunch_at_4pm_opener_is_closed():
    wh = hours.parse_library_hours("4 pm - 11 pm")
    assert hours.is_open_for(wh, TUE, time(12, 30), 60) is False
    assert hours.is_open_for(wh, TUE, time(19), 60) is True
    assert hours.is_open_for(wh, TUE, time(22, 30), 60) is False


def test_midday_closure():
    wh = hours.parse_library_hours("9 AM - 2 PM, 5 PM - 9 PM")
    assert hours.is_open_for(wh, TUE, time(15), 30) is False
    assert hours.is_open_for(wh, TUE, time(13), 30) is True
    assert hours.is_open_for(wh, TUE, time(13), 90) is False
    assert hours.format_for_day(wh, TUE) == "9:00 AM – 2:00 PM, 5:00 PM – 9:00 PM"


def test_two_ranges_comma():
    wh = hours.parse_library_hours("12 PM - 2 PM, 7 PM - 11 PM")
    assert wh.periods[1] == [(time(12), time(14)), (time(19), time(23))]
    assert wh.source == "library"


def test_day_ranges():
    wh = hours.parse_library_hours("11 AM – 10 PM (Mon–Thu)")
    assert wh.periods[0] == [(time(11), time(22))]
    assert 4 not in wh.periods and 6 not in wh.periods
    assert hours.format_for_day(wh, FRI) == "Closed"


def test_daily_midnight_close():
    wh = hours.parse_library_hours("Daily 8 am–12 am")
    assert wh.periods[3] == [(time(8), time(23, 59, 59))]
    assert hours.is_open_for(wh, TUE, time(22), 120) is True
    assert hours.format_for_day(wh, TUE) == "8:00 AM – 12:00 AM"


def test_late_close_after_midnight_splits():
    wh = hours.parse_library_hours("6 pm - 2 am")
    assert wh.periods[0] == [(time(0), time(2)), (time(18), time(23, 59, 59))]
    assert hours.is_open_for(wh, MON, time(23), 120) is True


@pytest.mark.parametrize("text", [
    "Confirm directly before visiting.Listed as daily 8 am–12 am",
    "Confirm directly before visiting",
    "",
    "9-6",
    "11:30 PM – 8:30 PM",
    "5 pm - 5 pm",
    "12 AM – 10 PM",
    "9 AM - 2 PM, 1 PM - 5 PM",
    "11 AM - 10 PM (Mon-Thu) and more",
])
def test_unparseable_returns_none(text):
    assert hours.parse_library_hours(text) is None
    assert hours.is_open_for(None, TUE, time(12), 60) is None


def test_inverted_ampm_rejected():
    assert hours.parse_library_hours("11:30 PM – 8:30 PM") is None


def test_equal_start_end_rejected():
    assert hours.parse_library_hours("9 AM - 9 AM") is None


def test_nnbsp_parsed():
    wh = hours.parse_library_hours("11:30 AM ‒ 10 PM")
    assert wh.periods[2] == [(time(11, 30), time(22))]
    wh = hours.parse_library_hours("5 pm — 9:30 pm")
    assert wh.periods[2] == [(time(17), time(21, 30))]


def test_format_week():
    roh = {"periods": [{"open": _g(d, 9), "close": _g(d, 18)} for d in range(1, 6)]
           + [{"open": _g(6, 9), "close": _g(6, 13)}]}
    assert hours.format_week(hours.from_google(roh)) == "9–6 Mon–Fri · 9–1 Sat · Closed Sun"
    assert hours.format_week(None) == "Hours unknown"


@pytest.mark.parametrize("roh", [
    {"periods": [{"open": {"hour": 9}}]},
    {"periods": [{"close": _g(1, 17)}]},
    {"periods": [{"open": _g(1, 9), "close": {"hour": 17}}]},
    {"periods": [{"open": None, "close": _g(1, 17)}]},
    {"periods": ["x"]},
])
def test_google_malformed_raises_value_error(roh):
    with pytest.raises(ValueError):
        hours.from_google(roh)


def test_prefix_day_spec():
    wh = hours.parse_library_hours("Mon-Fri 9 am-5 pm")
    assert wh.periods[0] == [(time(9), time(17))] and wh.periods[4] == [(time(9), time(17))]
    assert 5 not in wh.periods and 6 not in wh.periods


def test_wrapping_day_range():
    wh = hours.parse_library_hours("11 AM - 10 PM (Fri-Mon)")
    assert sorted(wh.periods) == [0, 4, 5, 6]


def test_sunday_night_spills_into_monday():
    wh = hours.from_google({"periods": [{"open": _g(0, 22), "close": _g(1, 1)}]})
    assert wh.periods[6] == [(time(22), time(23, 59, 59))]
    assert wh.periods[0] == [(time(0), time(1))]
    assert hours.is_open_for(wh, SUN, time(23, 30), 60) is True
    assert hours.is_open_for(wh, SUN, time(23, 30), 120) is False
