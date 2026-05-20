"""Parse all documents in an input folder and extract trip facts via AI."""

import json
import re
from pathlib import Path
from typing import Optional

import pdfplumber
from docx import Document as DocxDocument

from src.common.ai_provider import get_ai_client
from src.common.models import TripFacts, TripDay, TripHotel, TransportLeg


_EXTRACTION_PROMPT = """\
You are extracting travel facts from a travel document.

Read the document and return ONLY a JSON object with these exact fields:
{{
  "client_names": [],
  "num_guests": null,
  "departure_city": null,
  "destinations": [],
  "trip_start_date": null,
  "trip_end_date": null,
  "hotels": [],
  "transport_modes": [],
  "local_transport": null,
  "days": [],
  "dietary_restrictions": [],
  "food_allergies": [],
  "cuisine_preferences": []
}}

Field notes:
- client_names: list of traveller names
- num_guests: free-text string e.g. "2 adults" or "2 adults, 2 kids (ages 10, 8)" — null if not mentioned
- departure_city: home city they are travelling FROM — null if not mentioned
- destinations: ordered list of destination cities visited
- trip_start_date / trip_end_date: ISO YYYY-MM-DD (infer year from context; default to 2025 or 2026)
- hotels: list of {{"city": str, "hotel_name": str, "check_in": "YYYY-MM-DD"|null, "check_out": "YYYY-MM-DD"|null}}
- transport_modes: list of inter-city legs — extract as much ticket detail as you can find:
  {{"from_city": str, "to_city": str, "mode": "flight"|"train"|"cruise"|"bus"|"car", "date": "YYYY-MM-DD"|null,
    "operator": str|null, "ticket_number": str|null, "departure_time": "HH:MM"|null, "arrival_time": "HH:MM"|null,
    "from_terminal": str|null, "to_terminal": str|null, "booking_reference": str|null}}
  - operator: airline name, cruise line, train operator (e.g. "Qatar Airways", "MSC Cruises", "Trenitalia")
  - ticket_number: flight number, train number, ship name (e.g. "QR 552", "Frecciarossa 9601")
  - departure_time / arrival_time: local time in HH:MM (24h) at origin / destination
  - from_terminal / to_terminal: full airport or station name, include terminal if stated (e.g. "Mumbai Chhatrapati Shivaji International Airport T2", "Amsterdam Airport Schiphol")
  - booking_reference: PNR or confirmation number
- local_transport: trip-level default for how travellers get around within each city — free-text string e.g. "Public Transport", "Taxi + Walking", "Rental car" — null if not mentioned
- days: list of {{"day_number": int, "date": "YYYY-MM-DD"|null, "title": str|null, "overnight_city": str|null, "overnight_hotel": str|null, "activities": [str], "transport_note": str|null}}
- activities: plain strings e.g. "Visit Anne Frank House", "Check in to hotel"
- transport_note: day-specific transport override or detail — use when the day mentions something different from the trip-level default, e.g. "Taxi from airport to hotel", "Pre-arranged day trip, driver picks up from hotel at 8am", "Private transfer to port" — null if no day-specific transport info
- dietary_restrictions: e.g. "vegetarian", "halal", "Jain", "no pork"
- food_allergies: e.g. "nuts", "shellfish", "gluten", "dairy"
- cuisine_preferences: e.g. "local cuisine", "seafood", "Italian"

Rules:
- Return null for scalar fields you cannot find in the document; return [] for list fields
- Do NOT guess — only return facts explicitly stated in the document
- Return only valid JSON with no markdown fences and no explanation

Document ({filename}):
{text}"""


_MERGE_PROMPT = """\
You are merging travel facts extracted from {n} travel documents into one final fact sheet.

Documents:
{file_list}

Extracted facts from each document:
{facts_json}

Merge into a single JSON object using this schema:
{{
  "client_names": [],
  "num_guests": null,
  "departure_city": null,
  "destinations": [],
  "trip_start_date": null,
  "trip_end_date": null,
  "hotels": [],
  "transport_modes": [],
  "local_transport": null,
  "days": [],
  "dietary_restrictions": [],
  "food_allergies": [],
  "cuisine_preferences": []
}}

Merge rules:
- For scalar conflicts, prefer facts from the dict with the most entries in days (that is the main itinerary)
- Deduplicate transport legs by route (from_city + to_city + date) — when duplicates exist, merge their fields: prefer the entry with more non-null ticket details (operator, ticket_number, times, terminals, booking_reference)
- Deduplicate hotels by meaning (e.g. "Marriott Amsterdam" == "Amsterdam Marriott")
- Combine dietary_restrictions, food_allergies, cuisine_preferences from all dicts (union, no duplicates)
- days must come from the dict with the most complete day-by-day itinerary; preserve transport_note on each day
- Return only valid JSON with no markdown fences and no explanation"""


class FolderParser:
    """Parses all documents in a folder and returns consolidated TripFacts."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

    def __init__(self, ai_client=None):
        self._ai = ai_client if ai_client is not None else get_ai_client()

    def _find_files(self, folder: Path) -> list[Path]:
        seen: set[Path] = set()
        for f in folder.iterdir():
            if f.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                seen.add(f)
        return sorted(seen)

    def _extract_text(self, file: Path) -> Optional[str]:
        try:
            if file.suffix.lower() == ".pdf":
                return self._extract_pdf_text(file)
            if file.suffix.lower() == ".docx":
                return self._extract_docx_text(file)
        except Exception:
            pass
        return None

    def _extract_pdf_text(self, file: Path) -> Optional[str]:
        with pdfplumber.open(file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
        return text if text else None

    def _extract_docx_text(self, file: Path) -> Optional[str]:
        doc = DocxDocument(str(file))
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        return text if text else None

    def parse(self, folder: Path) -> tuple[TripFacts, list[str]]:
        """
        Parse all supported files in folder.
        Returns (TripFacts, warnings) where warnings is a list of filenames
        that could not be read.
        """
        files = self._find_files(folder)
        warnings: list[str] = []
        partials: list[tuple[str, dict]] = []

        for file in files:
            text = self._extract_text(file)
            if text is None:
                warnings.append(file.name)
                continue
            raw = self._extract_facts_from_file(text, file.name)
            partials.append((file.name, raw))

        if not partials:
            return TripFacts(), warnings

        if len(partials) == 1:
            facts = self._dict_to_trip_facts(partials[0][1])
        else:
            facts = self._merge_facts(partials)

        return facts, warnings

    def _extract_facts_from_file(self, text: str, filename: str) -> dict:
        prompt = _EXTRACTION_PROMPT.format(filename=filename, text=text[:40000])
        response = self._ai.complete(prompt, max_tokens=4096, temperature=0.1)
        return self._parse_json_response(response)

    def _merge_facts(self, partials: list[tuple[str, dict]]) -> TripFacts:
        file_list = "\n".join(f"- {name}" for name, _ in partials)
        facts_json = json.dumps(
            {name: data for name, data in partials},
            indent=2,
            ensure_ascii=False,
        )
        prompt = _MERGE_PROMPT.format(
            n=len(partials),
            file_list=file_list,
            facts_json=facts_json,
        )
        response = self._ai.complete(prompt, max_tokens=4096, temperature=0.1)
        merged = self._parse_json_response(response)
        return self._dict_to_trip_facts(merged)

    def _parse_json_response(self, response: str) -> dict:
        text = response.strip()
        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Fallback: extract JSON object embedded in prose
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _dict_to_trip_facts(self, data: dict) -> TripFacts:
        hotels = [
            TripHotel(
                city=h.get("city", ""),
                hotel_name=h.get("hotel_name", ""),
                check_in=h.get("check_in"),
                check_out=h.get("check_out"),
            )
            for h in (data.get("hotels") or [])
            if isinstance(h, dict) and h.get("city") and h.get("hotel_name")
        ]
        transport = [
            TransportLeg(
                from_city=t.get("from_city", ""),
                to_city=t.get("to_city", ""),
                mode=t.get("mode", "flight"),
                date=t.get("date"),
                operator=t.get("operator") or None,
                ticket_number=t.get("ticket_number") or None,
                departure_time=t.get("departure_time") or None,
                arrival_time=t.get("arrival_time") or None,
                from_terminal=t.get("from_terminal") or None,
                to_terminal=t.get("to_terminal") or None,
                booking_reference=t.get("booking_reference") or None,
            )
            for t in (data.get("transport_modes") or [])
            if isinstance(t, dict) and t.get("from_city") and t.get("to_city")
        ]
        days = [
            TripDay(
                day_number=d.get("day_number", i + 1),
                date=d.get("date"),
                title=d.get("title"),
                overnight_city=d.get("overnight_city"),
                overnight_hotel=d.get("overnight_hotel"),
                activities=[str(a) for a in (d.get("activities") or [])],
                transport_note=d.get("transport_note") or None,
            )
            for i, d in enumerate(data.get("days") or [])
            if isinstance(d, dict)
        ]
        return TripFacts(
            client_names=[str(n) for n in (data.get("client_names") or []) if n],
            num_guests=data.get("num_guests") or None,
            departure_city=data.get("departure_city") or None,
            destinations=[str(d) for d in (data.get("destinations") or []) if d],
            trip_start_date=data.get("trip_start_date") or None,
            trip_end_date=data.get("trip_end_date") or None,
            hotels=hotels,
            transport_modes=transport,
            local_transport=data.get("local_transport") or None,
            days=days,
            dietary_restrictions=[str(r) for r in (data.get("dietary_restrictions") or []) if r],
            food_allergies=[str(a) for a in (data.get("food_allergies") or []) if a],
            cuisine_preferences=[str(p) for p in (data.get("cuisine_preferences") or []) if p],
        )
