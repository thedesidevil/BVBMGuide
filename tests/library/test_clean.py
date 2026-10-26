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
