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


def test_last_plan_no_trailing_summary_is_included():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "PLAN A"
    ws["A2"] = "Hotel Alpha"; ws["B2"] = "3-Star"; ws["C2"] = "Twin"; ws["I2"] = 10000.0; ws["J2"] = 9000.0
    ws["I3"] = 10000.0; ws["J3"] = 9000.0; ws["L3"] = 500.0; ws["M3"] = 9500.0; ws["N3"] = 5.0
    ws["A4"] = "PLAN B"
    ws["A5"] = "Hotel Beta"; ws["B5"] = "4-Star"; ws["C5"] = "Double"; ws["I5"] = 20000.0; ws["J5"] = 18000.0
    # No summary row for Plan B — sheet ends here
    buf = io.BytesIO(); wb.save(buf); xlsx = buf.getvalue()
    result = parse_excel(xlsx, {})
    assert len(result.plans) == 2
    assert result.plans[1].label == "Plan B"
    assert result.plans[1].hotels[0].name == "Hotel Beta"


def test_plans_present_grouped_by_sections_false():
    """Existing PLAN-marker workbooks should have grouped_by_sections=False."""
    result = parse_excel(make_sample_xlsx(), CODES)
    assert result.grouped_by_sections is False


# Helper to build a minimal in-memory workbook for testing
def _make_wb_no_plans_with_sections():
    """Two section headers, two hotels each, no PLAN markers."""
    wb = openpyxl.Workbook()
    ws = wb.active
    # Row 1: requirements in A1
    ws.cell(1, 1).value = "Breakfast Included"
    # Row 2: section header  (col A text, col I blank)
    ws.cell(2, 1).value = "London (Jul 1 - Jul 5)"
    # Row 3 & 4: hotel rows under London
    ws.cell(3, 1).value = "Hotel Alpha"
    ws.cell(3, 2).value = "4-Star"
    ws.cell(3, 3).value = "Deluxe"
    ws.cell(3, 8).value = "nr"
    ws.cell(3, 9).value = 50000.0
    ws.cell(3, 10).value = 45000.0
    ws.cell(4, 1).value = "Hotel Beta"
    ws.cell(4, 2).value = "3-Star"
    ws.cell(4, 3).value = "Standard"
    ws.cell(4, 8).value = "br"
    ws.cell(4, 9).value = 40000.0
    ws.cell(4, 10).value = 36000.0
    # Row 5: section header
    ws.cell(5, 1).value = "Paris (Jul 6 - Jul 10)"
    # Row 6: hotel row under Paris
    ws.cell(6, 1).value = "Hotel Gamma"
    ws.cell(6, 2).value = "5-Star"
    ws.cell(6, 3).value = "Suite"
    ws.cell(6, 8).value = "nr"
    ws.cell(6, 9).value = 80000.0
    ws.cell(6, 10).value = 72000.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_wb_no_plans_flat():
    """Hotels with no section headers and no PLAN markers — one group."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(1, 1).value = "Any requirement"
    for i, name in enumerate(["Hotel X", "Hotel Y", "Hotel Z"], start=2):
        ws.cell(i, 1).value = name
        ws.cell(i, 2).value = "4-Star"
        ws.cell(i, 3).value = "Double"
        ws.cell(i, 8).value = "nr"
        ws.cell(i, 9).value = 30000.0
        ws.cell(i, 10).value = 27000.0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_no_plans_with_sections_groups_by_section():
    result = parse_excel(_make_wb_no_plans_with_sections(), codes={})
    assert result.grouped_by_sections is True
    assert len(result.plans) == 2
    london = result.plans[0]
    paris = result.plans[1]
    assert london.label == "London (Jul 1 - Jul 5)"  # raw label before normalization
    assert paris.label == "Paris (Jul 6 - Jul 10)"
    assert len(london.hotels) == 2
    assert len(paris.hotels) == 1
    assert london.pricing.total_online_price == 90000.0
    assert paris.pricing.total_online_price == 80000.0
    assert london.pricing.customer_discount == 0.0
    assert london.pricing.discounted_price == 90000.0
    assert london.pricing.discount_pct == 0.0


def test_no_plans_flat_all_hotels_in_one_plan():
    result = parse_excel(_make_wb_no_plans_flat(), codes={})
    assert result.grouped_by_sections is True
    assert len(result.plans) == 1
    assert result.plans[0].label == "All Hotels"
    assert len(result.plans[0].hotels) == 3
