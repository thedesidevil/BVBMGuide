from src.aigv2.google.overrides import FILE_NAME, PlaceOverrides, place_from_override


def _put(o, name="Hotel Baren", city="Grindelwald"):
    return o.put(name, city, "Baeren Hotel, The Bear Inn", 46.66, 7.86, "https://maps.app.goo.gl/x", cid="0x1:0x2")


def test_roundtrip_and_variants(tmp_path):
    o = PlaceOverrides(tmp_path / FILE_NAME)
    assert o.get("a", "b") is None and o.all() == {}
    _put(o)
    assert o.get("HOTEL BAREN", "grindelwald")["lat"] == 46.66
    assert o.get("Baeren Hotel, The Bear Inn", "Grindelwald") is not None  # by google name
    assert o.get("Hotel Baren", "Bern") is None
    assert PlaceOverrides(tmp_path / FILE_NAME).get("Hôtel Baren", "Grindelwald") is not None  # persisted, accent-folded


def test_corrupt_file_backed_up_not_lost(tmp_path):
    p = tmp_path / FILE_NAME
    p.write_text("{not json")
    o = PlaceOverrides(p)
    assert o.get("x", "y") is None
    assert (tmp_path / (FILE_NAME + ".bak")).read_text() == "{not json"
    _put(o)
    assert o.get("Hotel Baren", "Grindelwald")


def test_place_from_override(tmp_path):
    o = PlaceOverrides(tmp_path / FILE_NAME)
    pl = place_from_override(_put(o), "q")
    assert pl.match_ok and pl.hours is None and pl.maps_url == "https://maps.app.goo.gl/x" and pl.name.startswith("Baeren")
