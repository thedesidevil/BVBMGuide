from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class HotelRow:
    name: str
    category: str
    room_type: str
    cancellation: str
    meal_type: str
    online_price: float


@dataclass
class PlanPricing:
    total_online_price: float
    total_b2b_price: float
    customer_discount: float
    discounted_price: float
    discount_pct: float


@dataclass
class Plan:
    label: str
    hotels: list[HotelRow]
    pricing: PlanPricing


@dataclass
class UnknownCode:
    code: str
    hotel_name: str
    plan_label: str


@dataclass
class ParseResult:
    plans: list[Plan]
    unknown_codes: list[UnknownCode]
    not_found: list[dict]


@dataclass
class EnrichedHotel:
    official_name: str
    address: str
    phone: str
    rating: float
    rating_count: int
    maps_url: str
    photo_bytes: bytes | None
    description: str
    cancellation: str
    meal_type: str
    category: str
