from datetime import date

import pytest

from src.aigv2.models import Marker
from src.aigv2.money import FxRates, FxUnavailable, city_currency, format_price, parse_price, price_text
from src.library.ui.storage import LocalStorageBackend

DAY = date(2026, 10, 29)


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, rates=None, status=200):
        self.rates = rates or {}
        self.status = status
        self.gets = []

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        code = url.split("from=")[1].split("&")[0] if "from=" in url else params["from"]
        if code not in self.rates:
            return FakeResp({"message": "not found"}, 404)
        return FakeResp({"rates": {"INR": self.rates[code]}}, self.status)


class StubFx:
    def __init__(self, rates):
        self.rates = rates

    def rate(self, code, on):
        if code not in self.rates:
            raise FxUnavailable(code)
        return self.rates[code]


def test_parse_range():
    assert parse_price("€20-30", "EUR") == ("EUR", 20, 30)
    assert parse_price("€1,000–1,800 per person", "EUR") == ("EUR", 1000, 1800)
    assert parse_price("CHF 30 per person", "CHF") == ("CHF", 30, 30)
    assert parse_price("35,000 – 70,000 UZS per person", "UZS") == ("UZS", 35000, 70000)
    assert parse_price("฿300–฿400", "THB") == ("THB", 300, 400)
    assert parse_price("Rs. 800 - Rs. 1,500", "INR") == ("INR", 800, 1500)
    assert parse_price("₹200 to 400", "INR") == ("INR", 200, 400)
    assert parse_price("2000 LKR per person", "LKR") == ("LKR", 2000, 2000)
    assert parse_price("25 pp", "EUR") == ("EUR", 25, 25)


def test_tier_unknown():
    for t in ("€€", "moderate", "$$$", "", None, "Free"):
        assert parse_price(t, "EUR") is None


def test_ambiguous_rupee_unknown():
    assert parse_price("Rs. 500", "MUR") is None
    assert parse_price("₹500", "LKR") is None
    assert parse_price("MUR 500", "MUR") == ("MUR", 500, 500)
    assert parse_price("Rs. 500", "INR") == ("INR", 500, 500)


def test_mixed_currencies_unknown():
    assert parse_price("€20 or $30", "EUR") is None


def test_format_rounds_to_50():
    assert format_price("EUR", 25, 25, 93.4) == "€25 (~₹2,350)"
    assert format_price("EUR", 20, 30, 93.4) == "€20–30 (~₹1,850–2,800)"
    assert format_price("MUR", 500, 500, 1.9) == "MUR 500 (~₹950)"
    assert format_price("CHF", 30, 45, 105.0) == "CHF 30–45 (~₹3,150–4,750)"


def test_fx_cached(tmp_path):
    storage = LocalStorageBackend(tmp_path)
    s = FakeSession({"EUR": 93.4})
    fx = FxRates(storage, session=s)
    assert fx.rate("EUR", DAY) == 93.4
    assert fx.rate("EUR", DAY) == 93.4
    assert len(s.gets) == 1
    s2 = FakeSession()
    assert FxRates(storage, session=s2).rate("EUR", DAY) == 93.4
    assert s2.gets == []
    assert storage.exists("cache/fx/2026-10-29.json")


def test_fx_inr_is_one_and_missing_raises(tmp_path):
    s = FakeSession({})
    fx = FxRates(LocalStorageBackend(tmp_path), session=s)
    assert fx.rate("INR", DAY) == 1.0
    assert s.gets == []
    with pytest.raises(FxUnavailable):
        fx.rate("MUR", DAY)


def test_missing_price_marker():
    out = price_text({"price_range": "€€"}, "EUR", StubFx({"EUR": 93.4}), DAY)
    assert out == Marker(kind="PRICE_UNKNOWN", text="")
    assert price_text({}, "EUR", StubFx({}), DAY).kind == "PRICE_UNKNOWN"


def test_price_text_international_and_per_city_currency():
    fx = StubFx({"EUR": 93.4, "CHF": 105.0})
    assert price_text({"price_range": "€25 per person"}, "EUR", fx, DAY) == "€25 (~₹2,350)"
    assert price_text({"price_range": "CHF 30 per person"}, "CHF", fx, DAY) == "CHF 30 (~₹3,150)"
    assert price_text({"price_range": "25"}, "CHF", fx, DAY) == "CHF 25 (~₹2,650)"


def test_price_text_domestic_inr_only():
    fx = StubFx({})
    assert price_text({"price_range": "₹1,000–1,800 per person"}, "INR", fx, DAY) == "₹1,000–1,800"
    assert price_text({"price_range": "Rs. 800 - Rs. 1,500"}, "INR", fx, DAY) == "₹800–1,500"
    assert price_text({"price_range": "€20"}, "INR", fx, DAY).kind == "PRICE_UNKNOWN"


def test_price_text_fx_unavailable_shows_local_only():
    assert price_text({"price_range": "MUR 500"}, "MUR", StubFx({}), DAY) == "MUR 500"


def test_city_currency():
    assert city_currency("France") == "EUR"
    assert city_currency("Switzerland") == "CHF"
    assert city_currency("Mauritius") == "MUR"
    assert city_currency("India") == "INR"
    assert city_currency("Narnia") is None
    assert city_currency("France", {"currency": "xyz"}) == "XYZ"
