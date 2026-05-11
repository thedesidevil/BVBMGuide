"""PDF Parser for extracting itinerary data from client PDFs."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import fitz  # PyMuPDF

from src.common.models import DayActivity, HotelStay, ItineraryData, ItineraryDay

if TYPE_CHECKING:
    from src.common.ai_provider import AIClient

# Invisible / zero-width characters to strip from PDF text
_INVISIBLE = "​‌‍﻿­"

# Known cities/regions — used only by the regex fallback to detect cruise ports
# and transit stops in day titles.  The AI path doesn't need this list.
_KNOWN_CITIES = {
    # Mediterranean / cruise ports
    "Santorini", "Mykonos", "Corfu", "Athens", "Piraeus",
    "Amalfi", "Salerno", "Positano", "Sorrento", "Capri",
    "Kusadasi", "Ephesus", "Bodrum", "Istanbul",
    "Katakolon", "Olympia", "Dubrovnik", "Split", "Kotor",
    # Italy
    "Rome", "Florence", "Venice", "Milan", "Naples", "Pisa", "Siena", "Bologna",
    # France
    "Paris", "Nice", "Lyon", "Marseille", "Bordeaux", "Strasbourg",
    # Spain
    "Barcelona", "Madrid", "Seville", "Granada", "Malaga", "Valencia",
    # Netherlands / Belgium
    "Amsterdam", "Rotterdam", "Brussels", "Bruges", "Ghent",
    # Germany / Austria / Switzerland
    "Berlin", "Munich", "Hamburg", "Vienna", "Salzburg",
    "Zurich", "Geneva", "Lucerne", "Innsbruck",
    # UK
    "London", "Edinburgh", "Manchester", "Liverpool", "Oxford", "Cambridge",
    # Portugal
    "Lisbon", "Porto",
    # Middle East
    "Dubai", "Abu Dhabi", "Doha",
    # Asia
    "Tokyo", "Kyoto", "Osaka", "Hiroshima", "Nara",
    "Bangkok", "Phuket", "Chiang Mai", "Pattaya",
    "Singapore", "Kuala Lumpur", "Penang", "Langkawi",
    "Bali", "Ubud", "Seoul", "Busan", "Jeju",
    "Beijing", "Shanghai", "Hong Kong",
    "Hanoi", "Ho Chi Minh", "Da Nang", "Hoi An",
    # India
    "Mumbai", "Delhi", "Goa", "Jaipur", "Agra", "Bangalore",
    # Oceania
    "Sydney", "Melbourne", "Auckland", "Queenstown",
    # Americas
    "New York", "Los Angeles", "Las Vegas", "Miami", "Chicago",
    "Toronto", "Vancouver", "Cancun", "Lima", "Cusco",
    # Africa
    "Cairo", "Cape Town", "Nairobi", "Marrakech",
}

_AI_PROMPT = """\
You are an expert travel data extractor. Extract all information from the itinerary text below and return it as a single JSON object matching the schema exactly.

Rules:
- Extract ONLY what is explicitly stated or strongly implied in the text.
- Do NOT invent or guess any information.
- Use null for any field that cannot be determined from the text.
- For overnight_city / overnight_hotel on each day: determine where the client actually sleeps that night (a hotel city, "On Cruise" for cruise ship nights, or "Departure day" for the final departure day with no overnight).
- For hotel check_in_date / check_out_date: infer from which days the client is in that city.
- Optional activities are those explicitly marked as optional in the text.

Return ONLY valid JSON, no other text.

Schema:
{
  "client_name": "<string or null>",
  "num_guests": "<integer or null>",
  "destinations": ["<all cities/regions in travel order>"],
  "hotel_stays": [
    {
      "city": "<string>",
      "hotel_name": "<string>",
      "check_in_date": "<e.g. Apr 19, or null>",
      "check_out_date": "<e.g. Apr 22, or null>"
    }
  ],
  "trip_start_date": "<e.g. Apr 19, or null>",
  "trip_end_date": "<e.g. May 5, or null>",
  "dietary_preferences": ["<e.g. vegetarian>"],
  "food_allergies": ["<e.g. nuts, shellfish>"],
  "cuisine_preferences": ["<e.g. local cuisine, seafood>"],
  "budget_level": "<budget | mid-range | luxury, or null>",
  "special_occasions": ["<e.g. anniversary, honeymoon, birthday>"],
  "transport_mode": "<string or null>",
  "days": [
    {
      "day_number": 1,
      "date": "<e.g. Apr 19>",
      "title": "<day title>",
      "activities": [
        {
          "name": "<activity text>",
          "is_optional": false,
          "extra_cost": false
        }
      ],
      "overnight_city": "<city name | On Cruise | Departure day | null>",
      "overnight_hotel": "<hotel name or null>"
    }
  ]
}

Itinerary text:
{pdf_text}
"""


class ItineraryParser:
    """Parses client itinerary PDFs to extract structured data."""

    def __init__(self, pdf_path: str | Path, ai_client: Optional["AIClient"] = None):
        self.pdf_path = Path(pdf_path)
        self.ai_client = ai_client
        self.raw_text = ""
        self.pages_text: list[str] = []

    def parse(self) -> ItineraryData:
        """Parse the PDF — AI-first, with regex as silent fallback."""
        self._load_pdf()

        if self.ai_client:
            try:
                return self._parse_with_ai()
            except Exception:
                pass  # fall through to regex

        return self._parse_with_regex()

    def _load_pdf(self) -> None:
        doc = fitz.open(self.pdf_path)
        self.pages_text = [page.get_text() for page in doc]
        doc.close()
        self.raw_text = "\n".join(self.pages_text)

    def _clean(self, text: str) -> str:
        return text.translate(str.maketrans("", "", _INVISIBLE))

    # ------------------------------------------------------------------
    # AI path
    # ------------------------------------------------------------------

    def _parse_with_ai(self) -> ItineraryData:
        """Send full PDF text to AI and map the structured response to ItineraryData."""
        prompt = _AI_PROMPT.replace("{pdf_text}", self._clean(self.raw_text))
        response = self.ai_client.complete(prompt, max_tokens=8192, temperature=0)
        data = self._extract_json(response)
        return self._map_ai_response(data)

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from a response that may be wrapped in markdown code fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    def _map_ai_response(self, data: dict) -> ItineraryData:
        """Map a validated AI JSON response dict to ItineraryData."""
        hotel_stays = [
            HotelStay(
                city=h.get("city", ""),
                hotel_name=h.get("hotel_name", ""),
                check_in_date=h.get("check_in_date"),
                check_out_date=h.get("check_out_date"),
            )
            for h in (data.get("hotel_stays") or [])
            if h.get("city") and h.get("hotel_name")
        ]

        days = [
            ItineraryDay(
                day_number=d.get("day_number", i + 1),
                date=d.get("date"),
                title=d.get("title") or f"Day {d.get('day_number', i + 1)}",
                activities=[
                    DayActivity(
                        name=a.get("name", ""),
                        is_optional=bool(a.get("is_optional", False)),
                        extra_cost=bool(a.get("extra_cost", False)),
                    )
                    for a in (d.get("activities") or [])
                    if a.get("name")
                ],
                overnight_city=d.get("overnight_city"),
                overnight_hotel=d.get("overnight_hotel"),
            )
            for i, d in enumerate(data.get("days") or [])
        ]

        destinations: list[str] = data.get("destinations") or []
        hotel_name = hotel_stays[0].hotel_name if hotel_stays else None
        destination = " / ".join(destinations) if destinations else "Unknown"

        return ItineraryData(
            destination=destination,
            trip_title=None,
            client_name=data.get("client_name"),
            num_guests=data.get("num_guests"),
            duration_days=len(days),
            days=days,
            hotel_name=hotel_name,
            trip_start_date=data.get("trip_start_date"),
            trip_end_date=data.get("trip_end_date"),
            destinations=destinations,
            hotel_stays=hotel_stays,
            dietary_preferences=data.get("dietary_preferences") or [],
            food_allergies=data.get("food_allergies") or [],
            cuisine_preferences=data.get("cuisine_preferences") or [],
            budget_level=data.get("budget_level"),
            special_occasions=data.get("special_occasions") or [],
            transport_mode=data.get("transport_mode"),
        )

    # ------------------------------------------------------------------
    # Regex fallback path
    # ------------------------------------------------------------------

    def _parse_with_regex(self) -> ItineraryData:
        hotel_stays = self._extract_hotels()
        start_date, end_date = self._extract_date_range()
        days = self._extract_days()
        self._assign_overnight_locations(days, hotel_stays)
        destinations = self._extract_destinations(hotel_stays)
        dietary_prefs = self._extract_dietary()
        transport = self._extract_transport()
        client_name = self._extract_client_name()

        destination = " / ".join(destinations) if destinations else "Unknown"
        hotel_name = hotel_stays[0].hotel_name if hotel_stays else None

        return ItineraryData(
            destination=destination,
            trip_title=None,
            client_name=client_name,
            duration_days=len(days),
            days=days,
            hotel_name=hotel_name,
            trip_start_date=start_date,
            trip_end_date=end_date,
            destinations=destinations,
            hotel_stays=hotel_stays,
            dietary_preferences=dietary_prefs,
            transport_mode=transport,
        )

    # ------------------------------------------------------------------
    # Regex extractors (used by fallback path)
    # ------------------------------------------------------------------

    def _extract_hotels(self) -> list[HotelStay]:
        text = self._clean(self.raw_text)
        m = re.search(r"Hotels:\s*\n", text, re.IGNORECASE)
        if not m:
            return []
        hotels: list[HotelStay] = []
        hotel_line_re = re.compile(r"^([A-Z][a-zA-Z\s]+):\s*(.+)$")
        for line in text[m.end():].split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            lm = hotel_line_re.match(stripped)
            if lm:
                hotels.append(HotelStay(city=lm.group(1).strip(), hotel_name=lm.group(2).strip()))
            elif hotels:
                break
        return hotels

    def _extract_date_range(self) -> tuple[Optional[str], Optional[str]]:
        text = self._clean(self.raw_text)
        raw_dates = re.findall(r"Day \d+:\s+([A-Z][a-z]+ \d{1,2})", text)
        parsed = []
        for d in raw_dates:
            try:
                dt = datetime.strptime(d.strip(), "%b %d")
                parsed.append((d.strip(), dt))
            except ValueError:
                continue
        if not parsed:
            return None, None
        parsed.sort(key=lambda x: (x[1].month, x[1].day))
        return parsed[0][0], parsed[-1][0]

    def _extract_days(self) -> list[ItineraryDay]:
        text = self._clean(self.raw_text)
        header_re = re.compile(r"Day (\d+):\s+([A-Z][a-z]+ \d{1,2})\s*\n", re.MULTILINE)
        matches = list(header_re.finditer(text))
        if not matches:
            return []
        days: list[ItineraryDay] = []
        for i, match in enumerate(matches):
            day_num = int(match.group(1))
            day_text = text[match.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
            lines = [ln.strip() for ln in day_text.split("\n") if ln.strip()]
            if lines and lines[0].lower() not in ("day at a glance", "day at glance"):
                title = lines[0]
                activity_lines = [ln for ln in lines[1:] if ln.lower() not in ("day at a glance", "day at glance")]
            else:
                title = match.group(2).strip()
                activity_lines = [ln for ln in lines if ln.lower() not in ("day at a glance", "day at glance")]
            activities = []
            for line in activity_lines:
                clean = re.sub(r"^[●○•■▪\-\*–]\s*", "", line).strip()
                if not clean or len(clean) < 3:
                    continue
                activities.append(DayActivity(
                    name=clean,
                    is_optional=line.startswith("○") or "optional" in line.lower(),
                    extra_cost="extra cost" in line.lower(),
                ))
            days.append(ItineraryDay(day_number=day_num, date=match.group(2).strip(), title=title, activities=activities))
        return days

    def _assign_overnight_locations(self, days: list[ItineraryDay], hotel_stays: list[HotelStay]) -> None:
        hotel_by_city = {stay.city.lower(): stay for stay in hotel_stays}
        current_hotel: Optional[HotelStay] = hotel_stays[0] if hotel_stays else None
        on_cruise = False
        for day in days:
            title = day.title
            tl = title.lower()
            if any(kw in tl for kw in ("cruise boarding", "board cruise", "boarding cruise")):
                on_cruise = True
            if "disembark" in tl:
                on_cruise = False
            m = re.search(r"arrival in ([a-z]+)", tl)
            if m:
                candidate = m.group(1)
                for city_key, stay in hotel_by_city.items():
                    if city_key.startswith(candidate) or candidate.startswith(city_key.split()[0]):
                        current_hotel = stay
                        on_cruise = False
                        break
            m = re.search(r"→\s*([A-Za-z][A-Za-z\s]*)", title)
            if m:
                dest = re.split(r"[|(]", m.group(1).strip())[0].strip().lower()
                if "cruise" in dest:
                    on_cruise = True
                else:
                    for city_key, stay in hotel_by_city.items():
                        if city_key in dest or dest.startswith(city_key.split()[0]):
                            current_hotel = stay
                            on_cruise = False
                            break
            if any(kw in tl for kw in ("departure", "fly back")):
                day.overnight_city = "Departure day"
                day.overnight_hotel = None
            elif on_cruise:
                day.overnight_city = "On Cruise"
                day.overnight_hotel = None
            elif current_hotel:
                day.overnight_city = current_hotel.city
                day.overnight_hotel = current_hotel.hotel_name

    def _extract_destinations(self, hotel_stays: list[HotelStay]) -> list[str]:
        text = self._clean(self.raw_text)
        seen: set[str] = set()
        destinations: list[str] = []

        def _add(city: str) -> None:
            if city.lower() not in seen:
                destinations.append(city)
                seen.add(city.lower())

        for stay in hotel_stays:
            _add(stay.city)
        for title in re.findall(r"Day \d+:\s+[A-Z][a-z]+ \d{1,2}\s*\n(.+)\n", text, re.MULTILINE):
            for city in _KNOWN_CITIES:
                if city.lower() in title.lower():
                    _add(city)
        return destinations

    def _extract_dietary(self) -> list[str]:
        text = self._clean(self.raw_text)
        m = re.search(r"Dietary preference\s*[-:]\s*(.+)", text, re.IGNORECASE)
        if not m:
            return []
        return [p.strip() for p in re.split(r"[,/]|\band\b", m.group(1).strip()) if p.strip()]

    def _extract_transport(self) -> Optional[str]:
        text = self._clean(self.raw_text)
        m = re.search(r"Mode of transport\s*\n(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _extract_client_name(self) -> Optional[str]:
        text = self._clean(self.raw_text)
        for pattern in [
            r"Dear\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"Prepared for[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).strip()
        stem = self.pdf_path.stem
        for sep in ("-", "_"):
            parts = stem.split(sep)
            if len(parts) >= 2:
                candidate = parts[0].strip()
                reject = {"all", "inclusive", "guide", "itinerary", "final", "updated", "new", "draft", "for", "aig"}
                if any(w in reject for w in candidate.lower().split()):
                    continue
                if re.match(r"^[A-Za-z]+$", candidate) and len(candidate) >= 3:
                    return candidate
        return None

    def get_raw_text(self) -> str:
        return self.raw_text


def parse_itinerary(pdf_path: str | Path, ai_client: Optional["AIClient"] = None) -> ItineraryData:
    """Parse an itinerary PDF, using AI if a client is provided."""
    return ItineraryParser(pdf_path, ai_client=ai_client).parse()
