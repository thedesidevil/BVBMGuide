import re
from datetime import date, time

from .models import WeeklyHours

END_OF_DAY = time(23, 59, 59)
_DAY_MIN = 1440
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_LATE_CLOSE_MAX_MIN = 4 * 60


def _mins(t: time) -> int:
    return _DAY_MIN if t >= END_OF_DAY else t.hour * 60 + t.minute


def _from_mins(m: int) -> time:
    return END_OF_DAY if m >= _DAY_MIN else time(m // 60, m % 60)


def _add(periods: dict[int, list[tuple[time, time]]], weekday: int, start_min: int, end_min: int) -> None:
    if end_min > start_min:
        periods.setdefault(weekday, []).append((_from_mins(start_min), _from_mins(end_min)))


def _finish(periods: dict[int, list[tuple[time, time]]], source: str) -> WeeklyHours:
    return WeeklyHours(periods={d: sorted(p) for d, p in periods.items()}, source=source)


def from_google(regular_opening_hours: dict) -> WeeklyHours:
    try:
        return _from_google(regular_opening_hours)
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"malformed regularOpeningHours: {e!r}") from e


def _from_google(regular_opening_hours: dict) -> WeeklyHours:
    raw = (regular_opening_hours or {}).get("periods")
    if not raw:
        raise ValueError("regularOpeningHours has no periods")
    periods: dict[int, list[tuple[time, time]]] = {}
    for p in raw:
        o = p["open"]
        if "close" not in p:
            if o.get("day") == 0 and not o.get("hour") and not o.get("minute") and len(raw) == 1:
                for d in range(7):
                    _add(periods, d, 0, _DAY_MIN)
                continue
            raise ValueError("period without close is not a 24-hour place")
        c = p["close"]
        day = (o["day"] - 1) % 7
        start = o.get("hour", 0) * 60 + o.get("minute", 0)
        end = ((c["day"] - o["day"]) % 7) * _DAY_MIN + c.get("hour", 0) * 60 + c.get("minute", 0)
        if end <= start:
            raise ValueError("period closes before it opens")
        while end > start:
            piece_end = min(end, _DAY_MIN)
            _add(periods, day, start, piece_end)
            start, end = 0, end - _DAY_MIN
            day = (day + 1) % 7
    return _finish(periods, "google")


_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?"
_RANGE_RE = re.compile(rf"^{_TIME}\s*-\s*{_TIME}$")
_DAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"
_DAYSPEC = rf"{_DAY}(?:\s*-\s*{_DAY})?"
_PREFIX_RE = re.compile(rf"^(daily|every\s*day|{_DAYSPEC})\s*:?\s+(.+)$")
_SUFFIX_RE = re.compile(rf"^(.+?)\s*\(\s*(daily|{_DAYSPEC})\s*\)$")


def _clock(h: str, m: str | None, ap: str) -> int | None:
    hour, minute = int(h), int(m or 0)
    if not (1 <= hour <= 12) or minute > 59:
        return None
    return (hour % 12 + (12 if ap == "p" else 0)) * 60 + minute


def _days(spec: str) -> list[int] | None:
    if spec in ("daily",) or spec.replace(" ", "") == "everyday":
        return list(range(7))
    parts = [s.strip()[:3] for s in spec.split("-")]
    try:
        idx = [[d.lower() for d in _DAYS].index(p) for p in parts]
    except ValueError:
        return None
    if len(idx) == 1:
        return idx
    out, i = [idx[0]], idx[0]
    while i != idx[1]:
        i = (i + 1) % 7
        out.append(i)
    return out


def parse_library_hours(text: str) -> WeeklyHours | None:
    if not text:
        return None
    s = re.sub(r"[\s     ]+", " ", text).strip().lower()
    s = re.sub(r"[‐-―−﹘﹣－]", "-", s).rstrip(".")
    days = list(range(7))
    m = _SUFFIX_RE.match(s)
    if m:
        s, spec = m.group(1), m.group(2)
        days = _days(spec)
    else:
        m = _PREFIX_RE.match(s)
        if m:
            days, s = _days(m.group(1)), m.group(2)
    if days is None:
        return None
    spans: list[tuple[int, int]] = []
    for chunk in s.split(","):
        r = _RANGE_RE.match(chunk.strip())
        if not r:
            return None
        start = _clock(r.group(1), r.group(2), r.group(3))
        end = _clock(r.group(4), r.group(5), r.group(6))
        if start is None or end is None or start == 0 or start == end:
            return None
        if end == 0:
            end = _DAY_MIN
        elif end < start and end > _LATE_CLOSE_MAX_MIN:
            return None
        spans.append((start, end))
    if not spans:
        return None
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        if e1 < s1 or s2 < e1:
            return None
    periods: dict[int, list[tuple[time, time]]] = {}
    for d in days:
        for start, end in spans:
            if end > start:
                _add(periods, d, start, end)
            else:
                _add(periods, d, start, _DAY_MIN)
                _add(periods, (d + 1) % 7, 0, end)
    return _finish(periods, "library")


def _intervals(hours: WeeklyHours, weekday: int) -> list[tuple[int, int]]:
    out = [(_mins(a), _mins(b)) for a, b in hours.periods.get(weekday, [])]
    out += [(_DAY_MIN + _mins(a), _DAY_MIN + _mins(b)) for a, b in hours.periods.get((weekday + 1) % 7, [])]
    merged: list[list[int]] = []
    for a, b in sorted(out):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def is_open_for(hours: WeeklyHours | None, day: date, start: time, minutes: int) -> bool | None:
    if hours is None:
        return None
    s = start.hour * 60 + start.minute
    return any(a <= s and s + minutes <= b for a, b in _intervals(hours, day.weekday()))


def _fmt12(t: time) -> str:
    m = _mins(t) % _DAY_MIN
    h, mi = divmod(m, 60)
    return f"{h % 12 or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def is_24h(periods: list[tuple[time, time]]) -> bool:
    return periods == [(time(0), END_OF_DAY)]


def format_for_day(hours: WeeklyHours | None, day: date) -> str:
    if hours is None:
        return "Hours unknown"
    p = hours.periods.get(day.weekday())
    if not p:
        return "Closed"
    if is_24h(p):
        return "Open 24 hours"
    return ", ".join(f"{_fmt12(a)} – {_fmt12(b)}" for a, b in p)


def _compact(t: time, default_pm: bool) -> str:
    m = _mins(t) % _DAY_MIN
    h, mi = divmod(m, 60)
    out = f"{h % 12 or 12}" + (f":{mi:02d}" if mi else "")
    if (h >= 12) != default_pm:
        out += "pm" if h >= 12 else "am"
    return out


def format_week(hours: WeeklyHours | None) -> str:
    if hours is None:
        return "Hours unknown"
    groups: list[tuple[int, int, list[tuple[time, time]]]] = []
    for d in range(7):
        p = hours.periods.get(d, [])
        if groups and groups[-1][2] == p:
            groups[-1] = (groups[-1][0], d, p)
        else:
            groups.append((d, d, p))
    parts = []
    for a, b, p in groups:
        label = _DAYS[a] if a == b else f"{_DAYS[a]}–{_DAYS[b]}"
        if not p:
            text = "Closed"
        elif is_24h(p):
            text = "24 hours"
        else:
            text = " & ".join(f"{_compact(x, False)}–{_compact(y, True)}" for x, y in p)
        parts.append(f"{text} {label}")
    return " · ".join(parts)
