from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field


class WeeklyHours(BaseModel):
    periods: dict[int, list[tuple[time, time]]]
    source: Literal["google", "library"]


class Traveller(BaseModel):
    adults: int
    kids_ages: list[int] = Field(default_factory=list)
    notes: str = ""
    child_counts: dict[str, int] = Field(default_factory=dict)


class Diet(BaseModel):
    restrictions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    pure_veg: bool = False


class HotelStay(BaseModel):
    city: str
    hotel: str
    check_in: date
    check_out: date
    source: Literal["voucher", "notes", "itinerary", "answer"]
    check_in_time: Optional[time] = None
    check_out_time: Optional[time] = None
    kind: Literal["hotel", "resort", "cruise", "sleeper_train", "lodge"] = "hotel"
    meal_plan: Literal["none", "breakfast", "half_board", "full_board", "all_inclusive"] = "none"


class TransportLeg(BaseModel):
    kind: Literal["flight", "train", "bus", "boat", "other"]
    from_place: str
    to_place: str
    depart: Optional[datetime] = None
    arrive: Optional[datetime] = None
    ref: str = ""
    source: str
    pax_label: str = ""
    operator: str = ""
    number: str = ""
    seat: str = ""
    platform: str = ""


class Booking(BaseModel):
    name: str
    day: date
    time: Optional[str] = None
    source: str
    end_time: Optional[str] = None
    meeting_point: str = ""
    duration: str = ""
    instructions: list[str] = Field(default_factory=list)
    timed: bool = True
    pax_label: str = ""
    included_in_package: bool = False


class PlannedItem(BaseModel):
    name: str
    kind: Literal["attraction", "activity", "meal_out", "transfer", "free_time"]
    city: str
    time: Optional[str] = None
    slot_hint: Literal["morning", "afternoon", "evening", "any"] = "any"
    note: str = ""
    optional: bool = False
    booking_ref: Optional[str] = None
    locality: str = ""
    includes_meal: list[Literal["breakfast", "lunch", "dinner"]] = Field(default_factory=list)
    pickup_time: Optional[str] = None
    pickup_place: str = ""


class Stop(BaseModel):
    name: str
    minutes_from_prev: int
    suggested_stop_min: int
    km_from_prev: float


class TransitStep(BaseModel):
    line: str
    headsign: str
    board: str
    alight: str
    stops: int


class DayPlan(BaseModel):
    date: date
    title: str
    city: str
    items: list[PlannedItem] = Field(default_factory=list)
    meal_rules: list[str] = Field(default_factory=list)
    drive_stops: list[Stop] = Field(default_factory=list)


class OpenChoice(BaseModel):
    day: Optional[date] = None
    text: str
    options: list[str] = Field(default_factory=list)


class TripPlan(BaseModel):
    client_names: list[str]
    travellers: Traveller
    diet: Diet
    travel_modes: list[Literal["taxi", "public_transport", "self_drive", "private_driver"]]
    hotels: list[HotelStay]
    transport: list[TransportLeg]
    bookings: list[Booking]
    days: list[DayPlan]
    open_choices: list[OpenChoice]
    vague_days: list[date]
    commentary_removed: list[str]
    trip_scope: Literal["international", "domestic"]
    budget: str = ""
    occasion: str = ""
    additional_notes: str = ""


class Question(BaseModel):
    id: str
    kind: str
    text: str
    options: list[str] = Field(default_factory=list)
    day: Optional[date] = None


Answers = dict[str, str]


class Place(BaseModel):
    query: str
    place_id: str
    name: str
    address: str
    lat: float
    lng: float
    status: Literal["OPERATIONAL", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY", "UNKNOWN"]
    hours: Optional[WeeklyHours] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    maps_url: str
    fetched_at: datetime
    match_ok: bool
    verify_note: Optional[str] = None


class Marker(BaseModel):
    kind: Literal["ADD_RESTAURANT", "VERIFY", "PRICE_UNKNOWN", "WRITE_LETTER", "CHECK"]
    text: str

    def render(self) -> str:
        if self.kind == "ADD_RESTAURANT":
            return f"⚠ ADD RESTAURANT – {self.text}"
        if self.kind == "VERIFY":
            return f"⚠ VERIFY: {self.text}"
        if self.kind == "PRICE_UNKNOWN":
            return "⚠ PRICE UNKNOWN"
        if self.kind == "WRITE_LETTER":
            return "⚠ WRITE PERSONAL LETTER"
        return f"⚠ CHECK: {self.text}"


class Finding(BaseModel):
    rule: str
    severity: Literal["error", "warning"]
    message: str
    anchor_text: str = ""
    day: Optional[int] = None
