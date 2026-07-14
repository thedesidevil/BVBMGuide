from src.hotel_options.models import (
    HotelRow, PlanPricing, Plan, UnknownCode, ParseResult, EnrichedHotel, RoomSegment,
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

def test_hotel_row_new_fields_default_empty():
    h = HotelRow(
        name="Test", category="4-Star", room_type="Double",
        cancellation="Free", meal_type="Breakfast", online_price=50000.0,
    )
    assert h.inclusions == ""
    assert h.exclusions == ""

def test_plan_inclusions_default_empty():
    p = Plan(
        label="Plan A",
        hotels=[],
        pricing=PlanPricing(0, 0, 0, 0, 0),
    )
    assert p.inclusions == ""

def test_room_segment_fields():
    seg = RoomSegment(room_type="Beach Villa", dates="Dec 22-25", online_price=1178668.0)
    assert seg.room_type == "Beach Villa"
    assert seg.dates == "Dec 22-25"
    assert seg.online_price == 1178668.0
    assert seg.photo_bytes is None
    assert seg.inclusions == ""
    assert seg.exclusions == ""

def test_enriched_hotel_room_segments_default_empty():
    e = EnrichedHotel(
        official_name="Test", address="", phone="", rating=4.0,
        rating_count=100, maps_url="", photo_bytes=None,
        description="", cancellation="", meal_type="", category="",
    )
    assert e.room_segments == []
