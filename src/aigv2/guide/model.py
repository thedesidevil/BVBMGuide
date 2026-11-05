"""Renderer-agnostic guide model: plain JSON-serialisable data, no rendering logic.

Field choices follow .superpowers/lookfeel/PATTERNS.md (Components table) and sample_all.py.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Link(_M):
    text: str
    url: Optional[str] = None


class Fact(_M):
    label: str
    value: str
    link: Optional[Link] = None


class MarkerRef(_M):
    kind: Literal["ADD_RESTAURANT", "VERIFY", "PRICE_UNKNOWN", "WRITE_LETTER", "CHECK"]
    text: str


class Restaurant(_M):
    name: str
    maps_url: Optional[str] = None
    cuisines: list[str] = Field(default_factory=list)
    veg: bool = False
    text: str = ""
    must_try: str = ""
    hours: Optional[str] = None
    price: Union[str, MarkerRef, None] = None
    travel: Optional[str] = None


# ------------------------------------------------------------------ day components
class Opener(_M):
    type: Literal["Opener"] = "Opener"
    number: int
    weekday: str
    date: str
    title: list[str]
    intro: str = ""


class YourDay(_M):
    type: Literal["YourDay"] = "YourDay"


class JourneyStop(_M):
    label: str
    name: Link
    time: Optional[str] = None


class JourneyStrip(_M):
    type: Literal["JourneyStrip"] = "JourneyStrip"
    stops: list[JourneyStop]
    legs: list[str] = Field(default_factory=list)  # legs[i] joins stops[i] and stops[i+1]


class SightseeingCard(_M):
    type: Literal["SightseeingCard"] = "SightseeingCard"
    when: str
    part: Optional[str] = None
    name: Link
    subtitle: Optional[str] = None
    facts: list[Fact] = Field(default_factory=list)
    text: str = ""
    tips: list[str] = Field(default_factory=list)
    markers: list[MarkerRef] = Field(default_factory=list)


class BookingCard(_M):
    """Flight, transfer, boat, hotel check-in and return legs; `kind` is the eyebrow label."""
    type: Literal["BookingCard"] = "BookingCard"
    when: str
    kind: str
    prefix: Optional[str] = None
    title: Link
    subtitle: Optional[str] = None
    facts: list[Fact] = Field(default_factory=list)
    text: str = ""
    ref: Optional[str] = None
    note: Optional[str] = None


class SimpleCard(_M):
    type: Literal["SimpleCard"] = "SimpleCard"
    when: str
    part: Optional[str] = None
    heading: str
    text: str = ""


class ChecklistCard(_M):
    type: Literal["ChecklistCard"] = "ChecklistCard"
    when: str
    kind: Optional[str] = None
    title: Link
    lead: str = ""
    items: list[str] = Field(default_factory=list)


class Option(_M):
    label: str
    name: Link
    facts: list[Fact] = Field(default_factory=list)
    text: str = ""
    note: Optional[str] = None


class OptionCards(_M):
    type: Literal["OptionCards"] = "OptionCards"
    eyebrow: str
    heading: str
    chip: Optional[str] = None
    own_expense: bool = False
    options: list[Option]


class MealBlock(_M):
    type: Literal["MealBlock"] = "MealBlock"
    meal: Literal["breakfast", "lunch", "dinner"]
    eyebrow: str
    heading: str
    restaurants: list[Restaurant] = Field(default_factory=list)


class PlaceholderMeal(_M):
    type: Literal["PlaceholderMeal"] = "PlaceholderMeal"
    meal: Literal["breakfast", "lunch", "dinner"]
    eyebrow: str
    heading: str
    count: int = 3


class ReviewMarkerBlock(_M):
    type: Literal["ReviewMarkerBlock"] = "ReviewMarkerBlock"
    markers: list[MarkerRef]


# ------------------------------------------------------------------ reference components
class ReferenceOpener(_M):
    type: Literal["ReferenceOpener"] = "ReferenceOpener"
    eyebrow: str
    title: str
    intro: str = ""


class FactRowBlock(_M):
    type: Literal["FactRowBlock"] = "FactRowBlock"
    facts: list[Fact]


class TitledPara(_M):
    heading: str
    body: str


class TitledParas(_M):
    type: Literal["TitledParas"] = "TitledParas"
    items: list[TitledPara]


class ChecklistGroup(_M):
    title: str
    items: list[str]


class ChecklistGroups(_M):
    type: Literal["ChecklistGroups"] = "ChecklistGroups"
    groups: list[ChecklistGroup]


class TipPanel(_M):
    type: Literal["TipPanel"] = "TipPanel"
    title: str
    items: list[str] = Field(default_factory=list)
    columns: int = 1
    checks: bool = False


class NotePanel(_M):
    type: Literal["NotePanel"] = "NotePanel"
    title: str
    text: Optional[str] = None
    items: list[str] = Field(default_factory=list)


class App(_M):
    name: str
    use: str


class AppGrid(_M):
    type: Literal["AppGrid"] = "AppGrid"
    apps: list[App]


class NearbyPlace(_M):
    name: Link
    walk_min: Optional[int] = None
    drive_min: Optional[int] = None
    hours_text: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    markers: list[MarkerRef] = Field(default_factory=list)


class HotelPlaces(_M):
    hotel: Link
    city: str
    dates: str
    pharmacies: list[NearbyPlace] = Field(default_factory=list)
    groceries: list[NearbyPlace] = Field(default_factory=list)
    hospitals: list[NearbyPlace] = Field(default_factory=list)
    markers: list[MarkerRef] = Field(default_factory=list)


class PlaceGroups(_M):
    type: Literal["PlaceGroups"] = "PlaceGroups"
    hotels: list[HotelPlaces]


class Dish(_M):
    name: str
    desc: str
    where: list[Link] = Field(default_factory=list)


class DishGrid(_M):
    type: Literal["DishGrid"] = "DishGrid"
    dishes: list[Dish]


class Souvenir(_M):
    title: str
    what: str
    places: list[Link] = Field(default_factory=list)


class SouvenirGrid(_M):
    type: Literal["SouvenirGrid"] = "SouvenirGrid"
    categories: list[Souvenir]


class DosDonts(_M):
    type: Literal["DosDonts"] = "DosDonts"
    do: list[str]
    dont: list[str]


class Phrase(_M):
    local: str
    english: str


class PhraseTable(_M):
    type: Literal["PhraseTable"] = "PhraseTable"
    phrases: list[Phrase]


class EmergencyNumber(_M):
    service: str
    number: str


class EmergencyStrip(_M):
    type: Literal["EmergencyStrip"] = "EmergencyStrip"
    numbers: list[EmergencyNumber]
    dial: Optional[str] = None


class Contact(_M):
    eyebrow: str
    name: Link
    phone: Optional[str] = None
    note: Optional[str] = None


class ContactCards(_M):
    type: Literal["ContactCards"] = "ContactCards"
    cards: list[Contact]


# ------------------------------------------------------------------ letter / thank-you
class Letter(_M):
    type: Literal["Letter"] = "Letter"
    salutation: str
    paragraphs: list[str]
    signoff: str
    signature: str


class ThankYou(_M):
    type: Literal["ThankYou"] = "ThankYou"
    paragraphs: list[str]
    signoff: str
    signature: str


Component = Annotated[
    Union[Opener, YourDay, JourneyStrip, SightseeingCard, BookingCard, SimpleCard, ChecklistCard, OptionCards,
          MealBlock, PlaceholderMeal, ReviewMarkerBlock, ReferenceOpener, FactRowBlock, TitledParas,
          ChecklistGroups, TipPanel, NotePanel, AppGrid, PlaceGroups, DishGrid, SouvenirGrid, DosDonts,
          PhraseTable, EmergencyStrip, ContactCards, Letter, ThankYou],
    Field(discriminator="type")]


class Page(_M):
    kind: Literal["letter", "toc", "day", "reference", "thank_you"]
    title: str
    bookmark: str
    components: list[Component] = Field(default_factory=list)


class Guide(_M):
    client: str
    destination: str
    title: str
    subtitle: str
    pages: list[Page]
