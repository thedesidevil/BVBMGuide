import pytest

from src.library.ingest_core.clean import clean_extraction
from src.library.ingest_core.identity import item_key
from src.library.ingest_core.merge import FileMeta, merge_extraction
from src.library.ingest_core.prompt import CITY_LISTS, COUNTRY_LISTS
from datetime import date

# Only the fields the prompt makes mandatory (everything else omitted).
MANDATORY = {
    "restaurants": {"name": "Fake Trattoria", "city": "Rome"},
    "attractions": {"name": "Fake Ruins", "city": "Rome"},
    "hotels": {"name": "Fake Hotel", "city": "Rome"},
    "local_dishes": {"name": "Fake Stew", "city": "Rome"},
    "phrases": {"city": "Rome", "english": "Hello"},
    "souvenirs": {"item": "Fake Magnet", "city": "Rome"},
    "emergency_contacts": {"city": "Rome", "service": "Police"},
    "transport_options": {"city": "Rome", "mode": "Metro"},
    "route_guides": {"city": "Rome", "from": "Rome"},
    "season_notes": {"city": "Rome", "tip": "Summers are hot"},
    "safety_tips": {"cities": ["Rome"], "tip": "Watch for pickpockets"},
    "health_tips": {"cities": ["Rome"], "tip": "Tap water is safe"},
    "connectivity_tips": {"cities": ["Rome"], "tip": "Buy a local SIM"},
    "plugs": {"type": "F"},
    "tipping": {"tip": "Tipping is optional"},
    "dos_donts": {"tip": "Dress modestly in churches"},
    "scams": {"tip": "Beware fake petitions"},
    "insurance": {"tip": "Carry travel insurance"},
    "apps": {"name": "Fake Transit App"},
    "money": {"tip": "Cards widely accepted"},
    "embassies": {"name": "Fake Embassy"},
}
COUNTRY_ONLY = {"connectivity_tips": {"provider": "FakeSIM"}}


@pytest.mark.parametrize("name", CITY_LISTS)
def test_city_list_mandatory_only_item_is_kept(name):
    out, dropped = clean_extraction({name: [dict(MANDATORY[name])]})
    assert dropped == [] and len(out[name]) == 1


@pytest.mark.parametrize("name", COUNTRY_LISTS)
def test_country_list_mandatory_only_item_is_kept(name):
    item = dict(COUNTRY_ONLY.get(name) or MANDATORY[name])
    if name in ("phrases", "emergency_contacts", "transport_options"):
        item.pop("city", None)
    item.pop("cities", None)
    out, dropped = clean_extraction({"country_content": [{"country": "Italy", name: [item]}]})
    assert dropped == [] and len(out["country_content"][0][name]) == 1


def test_embassy_without_city_kept():
    out, dropped = clean_extraction({"country_content": [{"country": "Italy", "embassies": [
        {"name": "Fake Embassy", "address": "1 Fake St", "phone": "000"}]}]})
    assert dropped == [] and len(out["country_content"][0]["embassies"]) == 1


def test_sim_without_kind_kept():
    out, dropped = clean_extraction({"country_content": [{"country": "Italy", "connectivity_tips": [
        {"provider": "FakeSIM", "price_text": "EUR 10"}]}]})
    assert dropped == [] and len(out["country_content"][0]["connectivity_tips"]) == 1


def test_item_key_fallback_order():
    assert item_key("embassies", {"name": "E", "city": "Rome"}) == "e|rome"
    assert item_key("embassies", {"name": "E"}) == "e"
    assert item_key("route_guides", {"from": "A", "to": "B"}) == "a|b"
    assert item_key("route_guides", {"from": "A"}) == "a"
    assert item_key("emergency_contacts", {"service": "Police", "number": "112"}) == "police|112"
    assert item_key("emergency_contacts", {"number": "112"}) == "112"
    assert item_key("emergency_contacts", {"service": "Police"}) == "police"


# --- transport_options ---------------------------------------------------

def _meta(name="italy/a.docx"):
    return FileMeta(source_file=name, order_date=date(2025, 1, 1), fmt="new", folder="italy")


def _train(**kw):
    return {"city": "Rome", "mode": "Train", **kw}


def test_two_trains_with_different_pass_both_survive(memory_db):
    merge_extraction(memory_db, {"transport_options": [
        _train(recommended_pass="Trenitalia Pass"), _train(recommended_pass="Italo Pass")]}, _meta())
    assert len(memory_db.get_city_data("Rome")["transport_options"]) == 2


def test_two_trains_with_different_description_both_survive(memory_db):
    merge_extraction(memory_db, {"transport_options": [
        _train(description="Fast intercity"), _train(description="Slow regional")]}, _meta())
    assert len(memory_db.get_city_data("Rome")["transport_options"]) == 2


def test_duplicate_train_deduped_and_remerge_idempotent(memory_db):
    data = {"transport_options": [_train(recommended_pass="P"), _train(recommended_pass="P", cost="9")]}
    merge_extraction(memory_db, data, _meta())
    assert len(memory_db.get_city_data("Rome")["transport_options"]) == 1
    before = memory_db.get_city_data("Rome")
    s = merge_extraction(memory_db, {"transport_options": [_train(recommended_pass="P")]}, _meta())
    assert len(memory_db.get_city_data("Rome")["transport_options"]) == 1
    assert s.added == 0 and memory_db.get_city_data("Rome")["transport_options"][0]["recommended_pass"] == "P"
    assert before["transport_options"][0]["mode"] == "Train"


def test_prompt_sample_shape_transport_regression(memory_db):
    sample = {"city": "", "mode": "Metro", "description": "", "recommended_pass": "", "cost": "",
              "how_to_use": "", "covers": ""}
    metro = {**sample, "city": "Rome", "description": "Lines A, B", "recommended_pass": "Roma Pass"}
    bus = {**sample, "city": "Rome", "mode": "Bus", "description": "City buses"}
    train = {**sample, "city": "Rome", "mode": "Train", "description": "Regional"}
    train2 = {**sample, "city": "Rome", "mode": "Train", "description": "High speed"}
    merge_extraction(memory_db, {"transport_options": [metro, bus, train, train2]}, _meta())
    assert len(memory_db.get_city_data("Rome")["transport_options"]) == 4
