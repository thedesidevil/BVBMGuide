import zipfile

from src.library.ingest_core.clean import clean_extraction, is_v2_generated


def _reasons(dropped):
    return [d["reason"] for d in dropped]


def test_marker_item_dropped():
    data = {"safety_tips": [{"tip": "⚠ VERIFY: price"}, {"tip": "Keep copies of your passport"}]}
    out, dropped = clean_extraction(data)
    assert out["safety_tips"] == [{"tip": "Keep copies of your passport"}]
    assert _reasons(dropped) == ["marker"]
    assert dropped[0]["list"] == "safety_tips"
    assert "VERIFY" in dropped[0]["text"]


def test_verify_whole_word_only():
    data = {"safety_tips": [{"tip": "Always verifying fares is wise"}, {"tip": "Unverified taxis are risky"}]}
    out, dropped = clean_extraction(data)
    assert len(out["safety_tips"]) == 2 and dropped == []


def test_other_markers():
    data = {"restaurants": [{"name": "A", "note": "ADD RESTAURANT here"}, {"name": "B", "note": "price unknown"},
                            {"name": "C", "note": "CHECK: hours"}, {"name": "D", "note": "write personal letter"}]}
    out, dropped = clean_extraction(data)
    assert out["restaurants"] == [] and _reasons(dropped) == ["marker"] * 4


def test_chatter_dropped():
    data = {"safety_tips": [{"tip": "I would recommend a taxi at night"}, {"tip": "Let me know if you need more"}]}
    out, dropped = clean_extraction(data)
    assert out["safety_tips"] == [] and _reasons(dropped) == ["chatter", "chatter"]


def test_client_specific_dropped():
    data = {"safety_tips": [{"tip": "Ask your hotel for a map"}],
            "attractions": [{"name": "Tower", "description": "Day 2 visit the tower"},
                            {"name": "Museum", "description": "Booking ref ABC123"}]}
    out, dropped = clean_extraction(data)
    assert out["safety_tips"] == [] and out["attractions"] == []
    assert _reasons(dropped) == ["client_specific"] * 3


def test_normal_description_kept():
    r = {"name": "Prawn House", "highlights": ["Known for crispy prawns", "Great views"], "description": "Daylight views"}
    out, dropped = clean_extraction({"restaurants": [r]})
    assert out["restaurants"] == [r] and dropped == []


def test_no_identity_dropped():
    data = {"restaurants": [{"name": "  ", "cuisine": "Thai"}, {"name": "Good", "cuisine": "Thai"}]}
    out, dropped = clean_extraction(data)
    assert [r["name"] for r in out["restaurants"]] == ["Good"]
    assert _reasons(dropped) == ["no_identity"]


def test_country_content_cleaned_and_input_not_mutated():
    data = {"restaurants": [{"name": "Good"}],
            "country_content": {"Italy": {"safety_tips": [{"tip": "⚠ CHECK: x"}, {"tip": "Beware pickpockets"}]}},
            "other": 1}
    snapshot = repr(data)
    out, dropped = clean_extraction(data)
    assert repr(data) == snapshot
    assert out["country_content"]["Italy"]["safety_tips"] == [{"tip": "Beware pickpockets"}]
    assert out["other"] == 1
    assert _reasons(dropped) == ["marker"]


def _docx(path, custom_xml=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        if custom_xml is not None:
            z.writestr("docProps/custom.xml", custom_xml)


CUSTOM = ('<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">'
          '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="bvbm_run_id"><lpwstr>abc</lpwstr></property>'
          '</Properties>')


def test_is_v2_generated(tmp_path):
    a = tmp_path / "a.docx"
    _docx(a, CUSTOM)
    b = tmp_path / "b.docx"
    _docx(b)
    c = tmp_path / "c.docx"
    c.write_text("not a zip")
    d = tmp_path / "d.docx"
    _docx(d, "<broken")
    assert is_v2_generated(a) is True
    assert is_v2_generated(b) is False
    assert is_v2_generated(c) is False
    assert is_v2_generated(d) is False
    assert is_v2_generated(tmp_path / "missing.docx") is False


def _tip_kept(text):
    out, dropped = clean_extraction({"safety_tips": [{"tip": text}]})
    return len(out["safety_tips"]) == 1 and dropped == []


def _tip_reason(text):
    out, dropped = clean_extraction({"safety_tips": [{"tip": text}]})
    return [d["reason"] for d in dropped]


def test_lowercase_verify_and_check_kept():
    assert _tip_kept("Verify the taxi has a meter")
    assert _tip_kept("Double-check: carry cash")


def test_uppercase_markers_still_dropped():
    assert _tip_reason("⚠ VERIFY: price") == ["marker"]
    assert _tip_reason("CHECK: hours") == ["marker"]


def test_no_longer_not_client_specific():
    assert _tip_kept("Booking no longer possible")
    assert _tip_kept("Reservation no longer needed")
    assert _tip_reason("Booking no. 12345") == ["client_specific"]
    assert _tip_reason("Booking ref ABC") == ["client_specific"]
    assert _tip_reason("Confirmation number 9") == ["client_specific"]
    assert _tip_reason("Reservation ID 9") == ["client_specific"]


def test_day_of_the_dead_kept_and_ai_chatter_dropped():
    assert _tip_kept("Day of the Dead Museum")
    assert _tip_reason("as an AI language model") == ["chatter"]
