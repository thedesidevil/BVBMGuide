import io
import openpyxl
from src.hotel_options.parser import extract_filename_meta, parse_excel

CODES = {"nr": "Non-refundable", "br": "Breakfast included"}


def make_sample_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Hilton London"
    ws["B2"] = "5-Star"
    ws["C2"] = "King Room"
    ws["H2"] = "nr. br"
    ws["I2"] = 50000.0
    ws["J2"] = 45000.0
    # Plan A summary: col A blank, totals in I/J/L/M/N
    ws["I3"] = 50000.0
    ws["J3"] = 45000.0
    ws["L3"] = 3000.0
    ws["M3"] = 47000.0
    ws["N3"] = 6.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_filename_meta_standard():
    name, dest = extract_filename_meta("DO NOT SHARE_ Bushan_Accommodation Options_London.xlsx")
    assert name == "Bushan"
    assert dest == "London"


def test_extract_filename_meta_fallback():
    _, dest = extract_filename_meta("some_random_file.xlsx")
    assert dest == "file"


def test_parse_returns_one_plan():
    result = parse_excel(make_sample_xlsx(), CODES)
    assert len(result.plans) == 1
    assert result.plans[0].label == "Plan A"


def test_parse_hotel_decoded():
    result = parse_excel(make_sample_xlsx(), CODES)
    hotel = result.plans[0].hotels[0]
    assert hotel.name == "Hilton London"
    assert hotel.cancellation == "Non-refundable"
    assert hotel.meal_type == "Breakfast included"
    assert hotel.online_price == 50000.0


def test_parse_pricing():
    result = parse_excel(make_sample_xlsx(), CODES)
    pricing = result.plans[0].pricing
    assert pricing.total_online_price == 50000.0
    assert pricing.customer_discount == 3000.0
    assert pricing.discounted_price == 47000.0
    assert pricing.discount_pct == 6.0


def test_no_unknown_codes():
    result = parse_excel(make_sample_xlsx(), CODES)
    assert result.unknown_codes == []


def test_unknown_code_flagged():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Test Hotel"
    ws["B2"] = "3-Star"
    ws["C2"] = "Double"
    ws["H2"] = "xy"
    ws["I2"] = 10000.0
    ws["J2"] = 9000.0
    ws["I3"] = 10000.0
    ws["J3"] = 9000.0
    ws["L3"] = 0.0
    ws["M3"] = 10000.0
    ws["N3"] = 0.0
    buf = io.BytesIO()
    wb.save(buf)
    result = parse_excel(buf.getvalue(), CODES)
    assert len(result.unknown_codes) == 1
    assert result.unknown_codes[0].code == "xy"
