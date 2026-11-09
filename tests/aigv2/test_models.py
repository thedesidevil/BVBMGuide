from src.aigv2.config import load_settings
from src.aigv2.models import Marker
from src.common.ai_provider import _lookup_pricing


def _clear(monkeypatch):
    for k in ("AI_MODEL", "AI_MODEL_FAST", "AIGV2_MODEL_WRITE_DAYS"):
        monkeypatch.delenv(k, raising=False)


def test_settings_defaults(monkeypatch):
    _clear(monkeypatch)
    s = load_settings()
    assert s.models["write_days"] == "gpt-6-luna"
    assert s.models["qc_sense"] == "gpt-6.1-sol"
    assert s.walk_max_min == 10


def test_settings_step_override(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AIGV2_MODEL_WRITE_DAYS", "gpt-6.1-sol")
    assert load_settings().models["write_days"] == "gpt-6.1-sol"


def test_marker_render():
    assert Marker(kind="ADD_RESTAURANT", text="Lunch, Day 3, near Galata Tower").render() == "⚠ ADD RESTAURANT – Lunch, Day 3, near Galata Tower"
    assert Marker(kind="PRICE_UNKNOWN", text="").render() == "⚠ PRICE UNKNOWN"
    assert Marker(kind="VERIFY", text="x").render() == "⚠ VERIFY: x"
    assert Marker(kind="WRITE_LETTER", text="").render() == "⚠ WRITE PERSONAL LETTER"
    assert Marker(kind="CHECK", text="y").render() == "⚠ CHECK: y"


def test_pricing_known():
    assert _lookup_pricing("gpt-6.1-sol") == (2.0, 10.0)
    assert _lookup_pricing("gpt-6-luna") == (0.10, 0.50)


def test_gpt_6_sol_rejected(monkeypatch):
    import pytest
    from src.aigv2.config import Settings
    _clear(monkeypatch)
    monkeypatch.setenv("AIGV2_MODEL_WRITE_DAYS", "gpt-6-sol")
    with pytest.raises(ValueError, match="gpt-6-sol"):
        load_settings()
    monkeypatch.setenv("AIGV2_MODEL_WRITE_DAYS", "GPT-6.0-sol")
    with pytest.raises(ValueError, match="gpt-6-sol"):
        load_settings()
    with pytest.raises(ValueError):
        Settings(models={}, fallback_model="gpt-6-sol")
    monkeypatch.setenv("AIGV2_MODEL_WRITE_DAYS", "gpt-6.1-sol")
    assert load_settings().models["write_days"] == "gpt-6.1-sol"
