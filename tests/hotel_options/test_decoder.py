from src.hotel_options.decoder import decode_col_h

CODES = {"nr": "Non-refundable", "br": "Breakfast included", "hb": "Half board included"}


def test_empty_value():
    r = decode_col_h(None, CODES)
    assert r.cancellation == ""
    assert r.meal_type == ""
    assert r.unknowns == []


def test_nr_only():
    r = decode_col_h("nr", CODES)
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == ""


def test_br_only():
    r = decode_col_h("br", CODES)
    assert r.cancellation == ""
    assert r.meal_type == "Breakfast included"


def test_nr_dot_br():
    r = decode_col_h("nr. br", CODES)
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == "Breakfast included"


def test_date_dot_br():
    r = decode_col_h("26 jun. br", CODES)
    assert r.cancellation == "Free cancellation till 26 Jun"
    assert r.meal_type == "Breakfast included"


def test_unknown_code():
    r = decode_col_h("xy", CODES)
    assert "xy" in r.unknowns


def test_user_defined_code_is_meal():
    r = decode_col_h("hb", CODES)
    assert r.meal_type == "Half board included"
    assert r.unknowns == []


def test_plain_text_cancellation_and_all_inclusive():
    r = decode_col_h("Free cancellation before 23 Nov, All Inclusive", {})
    assert r.cancellation == "Free cancellation before 23 Nov"
    assert r.meal_type == "All Inclusive"
    assert r.unknowns == []


def test_plain_text_free_cancellation_and_full_board():
    r = decode_col_h("Free cancellation before 2 Dec, Full Board", {})
    assert r.cancellation == "Free cancellation before 2 Dec"
    assert r.meal_type == "Full Board"
    assert r.unknowns == []


def test_plain_text_non_refundable_keyword():
    r = decode_col_h("Non-refundable", {})
    assert r.cancellation == "Non-refundable"
    assert r.unknowns == []


def test_plain_text_fallback_does_not_affect_code_format():
    """Old-format codes still decode correctly — fallback never triggered."""
    r = decode_col_h("nr. br", {"nr": "Non-refundable", "br": "Breakfast included"})
    assert r.cancellation == "Non-refundable"
    assert r.meal_type == "Breakfast included"
    assert r.unknowns == []


def test_plain_text_unknown_segment_stays_unknown():
    """Unrecognised segment with no keywords goes to unknowns."""
    r = decode_col_h("SomeCode, All Inclusive", {})
    assert r.meal_type == "All Inclusive"
    assert "SomeCode" in r.unknowns
