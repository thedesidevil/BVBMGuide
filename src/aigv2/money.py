import math
import re
from datetime import date
from typing import Optional

import requests

from src.hotel_options.generator import format_indian_number
from src.library.ui.storage import StorageBackend

from .models import Marker

_SYMBOLS = {"€": "EUR", "£": "GBP", "₺": "TRY", "₹": "INR", "฿": "THB"}
_LOCAL_SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "TRY": "₺", "JPY": "¥", "THB": "฿", "INR": "₹"}
_DOLLAR_CODES = {"USD", "SGD", "AUD", "NZD", "HKD", "CAD"}
_RUPEE_COUNTRY_CODES = {"MUR", "LKR", "NPR"}
_ISO = {
    "EUR", "USD", "GBP", "TRY", "JPY", "CNY", "CHF", "THB", "AED", "IDR", "SGD", "INR", "MUR", "LKR", "NPR",
    "AUD", "NZD", "HKD", "CAD", "MYR", "VND", "KRW", "MOP", "UZS", "KZT", "CZK", "HUF", "PLN", "SEK", "NOK",
    "DKK", "ISK", "EGP", "MAD", "ZAR", "KES", "TZS", "QAR", "OMR", "SAR", "JOD", "BTN", "MVR", "PHP", "TWD",
    "KHR", "LAK", "MMK", "BRL", "MXN", "ARS", "CLP", "PEN", "COP", "GEL", "AMD", "AZN", "RON", "BGN", "RSD",
}
_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_TOKEN = re.compile(rf"(?P<num>{_NUMBER})|(?P<rs>\bRs\b\.?)|(?P<iso>\b[A-Z]{{3}}\b)|(?P<sym>[€£₺₹฿¥$])")

_EUROZONE = (
    "Austria Belgium Croatia Cyprus Estonia Finland France Germany Greece Ireland Italy Latvia Lithuania "
    "Luxembourg Malta Netherlands Portugal Slovakia Slovenia Spain Montenegro Andorra Monaco"
).split()
_COUNTRY_CURRENCY = {
    **{c: "EUR" for c in _EUROZONE},
    "Turkey": "TRY", "Turkiye": "TRY", "Türkiye": "TRY",
    "USA": "USD", "United States": "USD", "UK": "GBP", "United Kingdom": "GBP", "England": "GBP",
    "Scotland": "GBP", "Japan": "JPY", "Switzerland": "CHF", "Thailand": "THB",
    "UAE": "AED", "United Arab Emirates": "AED", "Dubai": "AED", "Indonesia": "IDR", "Bali": "IDR",
    "Singapore": "SGD", "India": "INR", "Mauritius": "MUR", "Sri Lanka": "LKR", "Nepal": "NPR",
}


class FxUnavailable(Exception):
    pass


def city_currency(country: str, shard: Optional[dict] = None) -> Optional[str]:
    if shard and isinstance(shard.get("currency"), str) and shard["currency"].strip():
        return shard["currency"].strip().upper()
    return _COUNTRY_CURRENCY.get((country or "").strip())


_REJECT = re.compile(
    r"\b(from|up\s*to|upto|starting|starts|min(imum)?|per\s+(dish|item|drink|course|dessert|kg|night|couple|pair|bottle|glass)"
    r"|for\s+(\d+|one|two|three|four|a\s+couple|couple|\w+\s+(people|persons|pax|guests)))\b",
    re.I,
)
_CONNECTOR = re.compile(r"^\s*(-|–|—|to)\s*$", re.I)
_NOISE_CODES = {"VAT", "PAX", "PER", "TAX", "AVG", "INC", "APX", "MIN", "MAX", "FOR"}


def parse_price(text: Optional[str], default_currency: str) -> Optional[tuple[str, float, float]]:
    if not text or _REJECT.search(text):
        return None
    default = (default_currency or "").upper()
    currencies: set[str] = set()
    numbers: list[tuple[float, int, int]] = []
    others: list[tuple[int, int]] = []
    for m in _TOKEN.finditer(text):
        if m.group("num"):
            numbers.append((float(m.group("num").replace(",", "")), m.start(), m.end()))
            continue
        others.append((m.start(), m.end()))
        if m.group("rs"):
            currencies.add("INR")
        elif m.group("iso"):
            iso = m.group("iso")
            if iso in _ISO:
                currencies.add(iso)
            elif iso not in _NOISE_CODES:
                return None
        else:
            sym = m.group("sym")
            if sym == "$":
                if default not in _DOLLAR_CODES:
                    return None
                currencies.add(default)
            elif sym == "¥":
                currencies.add("CNY" if default == "CNY" else "JPY")
            else:
                currencies.add(_SYMBOLS[sym])
    if len(currencies) > 1 or not 1 <= len(numbers) <= 2:
        return None
    if len(numbers) == 2:
        start, end = numbers[0][2], numbers[1][1]
        gap = "".join(c for i, c in enumerate(text[start:end], start) if not any(a <= i < b for a, b in others))
        if not _CONNECTOR.match(gap):
            return None
    code = next(iter(currencies), default)
    if not code or (code == "INR" and default != "INR"):
        return None
    low, high = numbers[0][0], numbers[-1][0]
    return code, min(low, high), max(low, high)


class FxRates:
    def __init__(self, backend: StorageBackend, session=None, today: Optional[date] = None):
        self.backend = backend
        self.session = session or requests.Session()
        self.today = today
        self._misses: dict[str, str] = {}

    def _fetch(self, code: str) -> float:
        errors = []
        sources = (
            (f"https://api.frankfurter.app/latest?from={code}&to=INR", lambda d: d["rates"]["INR"]),
            (f"https://open.er-api.com/v6/latest/{code}", lambda d: d["rates"]["INR"] if d["result"] == "success" else None),
        )
        for url, pick in sources:
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                value = pick(resp.json())
                if value:
                    return float(value)
                errors.append(f"{url}: no INR rate")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise FxUnavailable(f"no INR rate for {code}: " + "; ".join(errors))

    def rate(self, code: str, on: Optional[date] = None) -> float:
        code = code.upper()
        if code == "INR":
            return 1.0
        if code in self._misses:
            raise FxUnavailable(self._misses[code])
        key = f"cache/fx/{(self.today or date.today()).isoformat()}.json"
        cached = self.backend.read_json(key) or {}
        if code in cached:
            return float(cached[code])
        try:
            value = self._fetch(code)
        except FxUnavailable as exc:
            self._misses[code] = str(exc)
            raise
        cached[code] = value
        self.backend.write_json(key, cached)
        return value


def _num(x: float) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def _round_to(x: float, step: int) -> float:
    return math.floor(x / step + 0.5) * step


def _local(currency: str, low: float, high: float) -> str:
    sym = _LOCAL_SYMBOL.get(currency)
    lead = sym if sym else f"{currency} "
    return f"{lead}{_num(low)}" + ("" if low == high else f"–{_num(high)}")


def format_price(currency: str, low: float, high: float, inr_rate: float, round_to: int = 50) -> str:
    local = _local(currency, low, high)
    lo_v, hi_v = _round_to(low * inr_rate, round_to), _round_to(high * inr_rate, round_to)
    if lo_v <= 0 or hi_v <= 0:
        return local
    lo, hi = format_indian_number(lo_v), format_indian_number(hi_v)
    inr = lo if low == high else f"{lo}–{hi.lstrip('₹')}"
    return f"{local} (~{inr})"


def price_text(lib_restaurant: dict, city_currency: str, fx, day: date) -> "str | Marker":
    unknown = Marker(kind="PRICE_UNKNOWN", text="")
    parsed = parse_price(lib_restaurant.get("price_range"), city_currency)
    if parsed is None:
        return unknown
    code, low, high = parsed
    if (city_currency or "").upper() == "INR":
        return _local("INR", low, high) if code == "INR" else unknown
    try:
        rate = fx.rate(code, day)
    except FxUnavailable:
        return _local(code, low, high)
    return format_price(code, low, high, rate)
