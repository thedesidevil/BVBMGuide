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


def parse_price(text: Optional[str], default_currency: str) -> Optional[tuple[str, float, float]]:
    if not text:
        return None
    default = (default_currency or "").upper()
    currencies: set[str] = set()
    numbers: list[float] = []
    for m in _TOKEN.finditer(text):
        if m.group("num"):
            numbers.append(float(m.group("num").replace(",", "")))
        elif m.group("rs"):
            if default != "INR":
                return None
            currencies.add("INR")
        elif m.group("iso"):
            if m.group("iso") in _ISO:
                currencies.add(m.group("iso"))
        else:
            sym = m.group("sym")
            if sym == "$":
                currencies.add(default if default in _DOLLAR_CODES else "USD")
            elif sym == "¥":
                currencies.add("CNY" if default == "CNY" else "JPY")
            else:
                currencies.add(_SYMBOLS[sym])
    if len(currencies) > 1 or not 1 <= len(numbers) <= 2:
        return None
    code = next(iter(currencies), default)
    if not code or (code == "INR" and default in _RUPEE_COUNTRY_CODES):
        return None
    low, high = numbers[0], numbers[-1]
    return code, min(low, high), max(low, high)


class FxRates:
    def __init__(self, backend: StorageBackend, session=None):
        self.backend = backend
        self.session = session or requests.Session()

    def rate(self, code: str, on: date) -> float:
        code = code.upper()
        if code == "INR":
            return 1.0
        key = f"cache/fx/{on.isoformat()}.json"
        cached = self.backend.read_json(key) or {}
        if code in cached:
            return float(cached[code])
        try:
            resp = self.session.get(f"https://api.frankfurter.app/{on.isoformat()}?from={code}&to=INR", timeout=15)
            resp.raise_for_status()
            value = float(resp.json()["rates"]["INR"])
        except Exception as exc:
            raise FxUnavailable(f"no INR rate for {code} on {on}") from exc
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
    lo = format_indian_number(_round_to(low * inr_rate, round_to))
    hi = format_indian_number(_round_to(high * inr_rate, round_to))
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
