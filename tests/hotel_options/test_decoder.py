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
