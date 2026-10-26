from src.library.ingest_core.identity import city_shard_name, item_key, norm_key


def test_norm_key():
    assert norm_key("The  Café-Royal!") == "cafe royal"
    assert norm_key("São Paulo") == norm_key("sao paulo")


def test_item_key_alternatives():
    assert item_key("connectivity_tips", {"provider": "Airalo", "kind": "eSIM"}) == "airalo|esim"
    assert item_key("connectivity_tips", {"tip": "Buy a SIM"}) == "buy a sim"
    assert item_key("restaurants", {"name": "  "}) == ""


def test_city_shard_name():
    assert city_shard_name("  new   york ") == "New York"
