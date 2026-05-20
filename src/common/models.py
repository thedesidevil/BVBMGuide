"""Data models for the AIG Generator."""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

PLACEHOLDER_CLIENT_NAME = "[CLIENT NAME]"
PLACEHOLDER_HOTEL = "[HOTEL NAME]"
PLACEHOLDER_NUM_PAX = "[NUMBER OF GUESTS]"
PLACEHOLDER_DEPARTURE = "[DEPARTURE CITY]"
PLACEHOLDER_DATES = "[TRIP DATES]"


class DiningStyle(str, Enum):
    CASUAL = "casual"
    FINE_DINING = "fine_dining"
    STREET_FOOD = "street_food"
    CAFE = "cafe"
    FAMILY_FRIENDLY = "family_friendly"
    ROMANTIC = "romantic"


class FoodPreferences(BaseModel):
    """Structured food preferences parsed from user input."""
    
    dietary_restrictions: list[str] = Field(
        default_factory=list,
        description="e.g., vegetarian, vegan, no pork, no beef"
    )
    allergies: list[str] = Field(
        default_factory=list,
        description="e.g., nuts, shellfish, gluten"
    )
    cuisine_preferences: list[str] = Field(
        default_factory=list,
        description="e.g., local, seafood, Italian, spicy"
    )
    cuisine_dislikes: list[str] = Field(
        default_factory=list,
        description="Cuisines to avoid"
    )
    dining_styles: list[DiningStyle] = Field(
        default_factory=list,
        description="Preferred dining atmospheres"
    )
    budget_level: Optional[str] = Field(
        default=None,
        description="budget, mid-range, luxury"
    )
    special_occasions: list[str] = Field(
        default_factory=list,
        description="e.g., anniversary, birthday, honeymoon"
    )
    party_composition: list[str] = Field(
        default_factory=list,
        description="e.g., couple, family, with kids, solo"
    )
    raw_input: str = Field(
        default="",
        description="Original user input for reference"
    )


class DayActivity(BaseModel):
    """A single activity within a day."""
    
    name: str
    description: Optional[str] = None
    is_optional: bool = False
    extra_cost: bool = False


class ItineraryDay(BaseModel):
    """A single day in the itinerary."""

    day_number: int
    title: str
    date: Optional[str] = None          # e.g. "Apr 19" from the day header
    theme: Optional[str] = None
    activities: list[DayActivity] = Field(default_factory=list)
    overnight_city: Optional[str] = None   # city they sleep in that night
    overnight_hotel: Optional[str] = None  # hotel name for that night


class HotelStay(BaseModel):
    """A hotel stay at one city on the trip."""

    city: str
    hotel_name: str
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None


class ItineraryData(BaseModel):
    """Parsed data from an itinerary PDF."""

    destination: str
    trip_title: Optional[str] = None
    client_name: Optional[str] = None
    duration_days: int
    days: list[ItineraryDay] = Field(default_factory=list)

    # Fields that may need to be collected from user
    hotel_name: Optional[str] = None
    trip_start_date: Optional[str] = None
    trip_end_date: Optional[str] = None

    # Richer fields extracted from PDF when available
    destinations: list[str] = Field(default_factory=list)
    hotel_stays: list[HotelStay] = Field(default_factory=list)
    dietary_preferences: list[str] = Field(default_factory=list)
    food_allergies: list[str] = Field(default_factory=list)
    cuisine_preferences: list[str] = Field(default_factory=list)
    budget_level: Optional[str] = None
    transport_mode: Optional[str] = None
    num_guests: Optional[int] = None
    special_occasions: list[str] = Field(default_factory=list)


class UserInputs(BaseModel):
    """All inputs collected from the user."""
    
    itinerary: ItineraryData
    hotel_name: str
    food_preferences: FoodPreferences
    client_names: list[str] = Field(default_factory=list)
    trip_dates: Optional[str] = None
    additional_notes: Optional[str] = None


class Restaurant(BaseModel):
    """A restaurant from the library or curated."""
    
    name: str
    location: str
    cuisine_type: list[str] = Field(default_factory=list)
    price_range: Optional[str] = None
    ambience: Optional[str] = None
    must_try_dishes: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    google_maps_link: Optional[str] = None
    best_for: list[str] = Field(default_factory=list)
    vegetarian_friendly: bool = False
    pure_vegetarian: bool = False  # Entire restaurant is vegetarian (no meat/fish served)
    is_curated: bool = False  # True if not from library
    source_file: Optional[str] = None  # Which library file it came from


class MealRecommendation(BaseModel):
    """Restaurant recommendations for a meal."""
    
    meal_type: str  # "lunch" or "dinner"
    options: list[Restaurant] = Field(default_factory=list)


class AIGDay(BaseModel):
    """A fully enriched day for the AIG output."""

    day_number: int
    date: Optional[str] = None
    day_name: Optional[str] = None  # e.g. "Monday"
    title: str

    morning_activities: list[str] = Field(default_factory=list)
    afternoon_activities: list[str] = Field(default_factory=list)
    evening_activities: list[str] = Field(default_factory=list)

    lunch_recommendations: MealRecommendation = Field(
        default_factory=lambda: MealRecommendation(meal_type="lunch")
    )
    dinner_recommendations: MealRecommendation = Field(
        default_factory=lambda: MealRecommendation(meal_type="dinner")
    )

    overnight_location: Optional[str] = None


class ClientInfoRow(BaseModel):
    """One row in the client info trip summary table."""
    city: str
    dates: str
    hotel: str
    hotel_maps_link: str
    transport: str


class ClientInfoPage(BaseModel):
    """Structured client information page."""
    client_names: list[str]
    num_pax: Optional[str] = None
    departure_city: Optional[str] = None
    dietary_preferences: Optional[str] = None
    trip_summary_rows: list[ClientInfoRow] = Field(default_factory=list)


class ImportantPlace(BaseModel):
    """A nearby essential service (grocery, pharmacy, hospital)."""
    name: str
    category: str  # "grocery" | "pharmacy" | "hospital"
    address: Optional[str] = None
    hours: Optional[str] = None
    google_maps_link: Optional[str] = None
    phone: Optional[str] = None


class ImportantPlacesSection(BaseModel):
    """Important places grouped by city/hotel."""
    city: str
    hotel_name: str
    places: list[ImportantPlace] = Field(default_factory=list)


class QCIssue(BaseModel):
    """A single unresolved QC issue recorded for the QC Issues page."""
    section: str
    descriptions: list[str]


class AIGDocument(BaseModel):
    """Complete AIG document structure."""

    title: str
    subtitle: Optional[str] = None
    client_names: list[str]
    destination: str
    hotel_name: str
    hotel_maps_link: Optional[str] = None
    trip_dates: Optional[str] = None

    client_info: Optional[ClientInfoPage] = None
    days: list[AIGDay] = Field(default_factory=list)

    # Supplementary sections
    must_try_dishes: Optional[str] = None
    important_places_structured: list[ImportantPlacesSection] = Field(default_factory=list)
    souvenir_guide: Optional[str] = None
    cultural_etiquette: Optional[str] = None
    packing_list: Optional[str] = None
    safety_contacts: Optional[str] = None
    mobile_connectivity: Optional[str] = None
    health_vaccination: Optional[str] = None
    getting_around: Optional[str] = None
    thank_you_page: Optional[str] = None

    # Unresolved QC issues — written as final page in DOCX if non-empty
    unresolved_qc_issues: list[QCIssue] = Field(default_factory=list)


class TripDay(BaseModel):
    """One day in the trip, for human-editable trip_facts.json."""
    day_number: int
    date: Optional[str] = None           # ISO YYYY-MM-DD
    title: Optional[str] = None
    overnight_city: Optional[str] = None
    overnight_hotel: Optional[str] = None
    activities: list[str] = Field(default_factory=list)


class TripHotel(BaseModel):
    """A hotel stay, for human-editable trip_facts.json."""
    city: str
    hotel_name: str
    check_in: Optional[str] = None       # ISO YYYY-MM-DD
    check_out: Optional[str] = None      # ISO YYYY-MM-DD


class TransportLeg(BaseModel):
    """One transport leg between destinations."""
    from_city: str
    to_city: str
    mode: str                            # flight, train, cruise, bus, car
    date: Optional[str] = None          # ISO YYYY-MM-DD


class TripFacts(BaseModel):
    """All facts needed to generate an AIG. Saved as trip_facts.json for user review."""
    client_names: list[str] = Field(default_factory=list)
    num_guests: Optional[str] = None    # free text e.g. "2 adults, 2 kids (10, 8)"
    departure_city: Optional[str] = None
    destinations: list[str] = Field(default_factory=list)
    trip_start_date: Optional[str] = None   # ISO YYYY-MM-DD
    trip_end_date: Optional[str] = None     # ISO YYYY-MM-DD
    hotels: list[TripHotel] = Field(default_factory=list)
    transport_modes: list[TransportLeg] = Field(default_factory=list)
    days: list[TripDay] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)
    food_allergies: list[str] = Field(default_factory=list)
    cuisine_preferences: list[str] = Field(default_factory=list)

    def missing_required(self) -> list[str]:
        """Return names of required fields that are empty or null."""
        missing = []
        if not self.client_names:
            missing.append("client_names")
        if not self.destinations:
            missing.append("destinations")
        if not self.trip_start_date:
            missing.append("trip_start_date")
        if not self.trip_end_date:
            missing.append("trip_end_date")
        if not self.days:
            missing.append("days")
        if not self.hotels:
            missing.append("hotels")
        return missing

    def is_ready_for_generation(self) -> bool:
        return len(self.missing_required()) == 0

