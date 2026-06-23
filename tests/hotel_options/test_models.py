from src.hotel_options.models import (
    HotelRow, PlanPricing, Plan, UnknownCode, ParseResult, EnrichedHotel,
)

def test_hotel_row_fields():
    h = HotelRow(
        name="Hilton London",
        category="5-Star",
        room_type="King Room",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        online_price=50000.0,
    )
    assert h.name == "Hilton London"
    assert h.online_price == 50000.0

def test_plan_pricing_fields():
    p = PlanPricing(
        total_online_price=100000.0,
        total_b2b_price=90000.0,
        customer_discount=5000.0,
        discounted_price=95000.0,
        discount_pct=5.0,
    )
    assert p.discounted_price == 95000.0

def test_parse_result_fields():
    r = ParseResult(plans=[], unknown_codes=[], not_found=[])
    assert r.plans == []

def test_enriched_hotel_photo_optional():
    e = EnrichedHotel(
        official_name="Hilton London Kensington",
        address="179 Holland Park Ave",
        phone="+44 20 7602 3355",
        rating=4.2,
        rating_count=1847,
        maps_url="https://maps.google.com/?cid=123",
        photo_bytes=None,
        description="A refined hotel.",
        cancellation="Non-refundable",
        meal_type="Breakfast included",
        category="5-Star",
    )
    assert e.photo_bytes is None
