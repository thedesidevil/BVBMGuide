import io
from docx import Document
from src.hotel_options.generator import format_indian_number, build_document
from src.hotel_options.models import Plan, PlanPricing, HotelRow, EnrichedHotel


def test_format_indian_number():
    assert format_indian_number(176622.0) == "₹1,76,622"
    assert format_indian_number(191022.0) == "₹1,91,022"
    assert format_indian_number(3000.0) == "₹3,000"
    assert format_indian_number(100.0) == "₹100"


def _make_plan() -> Plan:
    hotel = HotelRow(
        name="Test Hotel", category="4-Star", room_type="Double",
        cancellation="Non-refundable", meal_type="Breakfast included", online_price=50000.0,
    )
    pricing = PlanPricing(
        total_online_price=50000.0, total_b2b_price=45000.0,
        customer_discount=3000.0, discounted_price=47000.0, discount_pct=6.0,
    )
    return Plan(label="Plan A", hotels=[hotel], pricing=pricing)


def _make_enriched() -> EnrichedHotel:
    return EnrichedHotel(
        official_name="Test Hotel Official", address="123 Test St, London",
        phone="+44 20 1234 5678", rating=4.1, rating_count=500,
        maps_url="https://maps.google.com/?cid=1", photo_bytes=None,
        description="A great hotel.", cancellation="Non-refundable",
        meal_type="Breakfast included", category="4-Star",
    )


def test_build_document_returns_bytes():
    doc_bytes = build_document(
        plans=[_make_plan()],
        enriched_map={"Test Hotel": _make_enriched()},
        client_name="Alice",
        destination="London",
        letterhead_path="/nonexistent/letterhead.docx",
    )
    assert isinstance(doc_bytes, bytes)
    assert len(doc_bytes) > 0


def test_build_document_contains_plan_and_destination():
    doc_bytes = build_document(
        plans=[_make_plan()],
        enriched_map={"Test Hotel": _make_enriched()},
        client_name="Alice",
        destination="London",
        letterhead_path="/nonexistent/letterhead.docx",
    )
    doc = Document(io.BytesIO(doc_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Plan A" in full_text
    assert "London" in full_text
    assert "Alice" in full_text


def test_format_indian_number_small():
    assert format_indian_number(500.0) == "₹500"
