"""QC engine — section-level and document-level validation."""

import json
import re
from typing import Optional

from .models import (
    AIGDay, AIGDocument, ClientInfoPage, FoodPreferences,
    ImportantPlacesSection, QCIssue,
)


class SectionQC:
    """Validates individual sections during generation. All methods return list[str] — empty = pass."""

    def __init__(self, ai_client=None):
        self._client = ai_client  # optional; only needed for check_supplementary

    # ------------------------------------------------------------------
    # Deterministic checks
    # ------------------------------------------------------------------

    def check_title(self, title: str, destination: str) -> list[str]:
        issues = []
        if not title or not title.strip():
            issues.append("Title is empty.")
            return issues
        t = title.strip()
        generic_patterns = [
            f"all inclusive guide - {destination}".lower(),
            f"all inclusive guide {destination}".lower(),
            "all inclusive guide",
        ]
        if any(t.lower() == p for p in generic_patterns):
            issues.append(f"Title '{t}' is generic. Must be creative and destination-evocative.")
        words = t.split()
        if len(words) < 3:
            issues.append(f"Title '{t}' is too short (< 3 words).")
        if len(words) > 12:
            issues.append(f"Title '{t}' is too long (> 12 words).")
        return issues

    def check_client_info(self, section: ClientInfoPage) -> list[str]:
        issues = []
        if not section.client_names or all(
            "[" in n for n in section.client_names
        ):
            issues.append("Client names are missing or all placeholders.")
        if not section.trip_summary_rows:
            issues.append("Trip summary table has no rows.")
        for row in section.trip_summary_rows:
            if not row.hotel or "[" in row.hotel:
                issues.append(f"Hotel missing for city '{row.city}'.")
            if not row.hotel_maps_link:
                issues.append(f"Hotel Maps link missing for city '{row.city}'.")
        return issues

    def check_day_header(self, day: AIGDay) -> list[str]:
        issues = []
        if not day.date or "[" in (day.date or ""):
            issues.append(f"Day {day.day_number}: date is missing or a placeholder.")
        if not day.day_name or "[" in (day.day_name or ""):
            issues.append(f"Day {day.day_number}: day name (Monday etc.) is missing.")
        if not day.title or not day.title.strip():
            issues.append(f"Day {day.day_number}: title is empty.")
        return issues

    def check_day_restaurants(
        self,
        day: AIGDay,
        recent_restaurant_names: Optional[list[str]] = None,
    ) -> list[str]:
        issues = []
        recent = recent_restaurant_names or []

        for meal in (day.lunch_recommendations, day.dinner_recommendations):
            label = f"Day {day.day_number} {meal.meal_type}"
            if len(meal.options) < 3:
                issues.append(
                    f"{label}: only {len(meal.options)} restaurant option(s); need ≥3."
                )
            for r in meal.options:
                if not r.google_maps_link:
                    issues.append(f"{label} — '{r.name}': missing Google Maps link.")
                if not r.hours:
                    issues.append(f"{label} — '{r.name}': missing opening hours.")
                if not r.distance_from_hotel:
                    issues.append(f"{label} — '{r.name}': missing distance from hotel.")
                # Rotation: same restaurant >2x in the window passed by caller
                count = recent.count(r.name)
                if count >= 2:
                    issues.append(
                        f"{label} — '{r.name}': appears {count} times in the last 3 days (max 2)."
                    )
        return issues

    def check_important_places(self, section: ImportantPlacesSection) -> list[str]:
        issues = []
        categories = [p.category for p in section.places]
        for required in ("grocery", "pharmacy", "hospital"):
            if required not in categories:
                issues.append(
                    f"Important Places for {section.city}: no '{required}' listed."
                )
        for place in section.places:
            if not place.hours:
                issues.append(
                    f"Important Places — '{place.name}' ({place.category}): missing hours."
                )
            if not place.google_maps_link:
                issues.append(
                    f"Important Places — '{place.name}' ({place.category}): missing Maps link."
                )
        return issues

    # ------------------------------------------------------------------
    # AI-based check (requires client)
    # ------------------------------------------------------------------

    def check_supplementary(
        self,
        section_name: str,
        content: str,
        destination: str,
        prefs: FoodPreferences,
    ) -> list[str]:
        """Use AI to spot quality issues in a supplementary section. Returns [] if client not set."""
        if not self._client or not content:
            return []

        dietary = ", ".join(prefs.dietary_restrictions) if prefs.dietary_restrictions else "none"
        prompt = f"""You are a QC reviewer for a premium travel guide section.

Section: {section_name}
Destination: {destination}
Client dietary restrictions: {dietary}

Content to review:
---
{content[:3000]}
---

Check ONLY for these specific problems:
1. Content is generic / not specific to {destination}
2. Dietary restrictions ({dietary}) are violated or ignored
3. Factual impossibilities (e.g. reversed hours like "11:30 PM – 9:30 AM")
4. Section is clearly incomplete (fewer than 3 items where more are expected)

Return a JSON array of problem strings. Return [] if no problems found.
Return ONLY valid JSON, no other text."""

        try:
            response = self._client.complete(prompt)
            text = response.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            problems = json.loads(text)
            if isinstance(problems, list):
                return [str(p) for p in problems]
        except Exception:
            pass
        return []


class DocumentQC:
    """Final pass on a complete AIGDocument. Returns list[QCIssue]."""

    MANDATORY_SECTIONS = [
        ("client_info", "Client Information Page"),
        ("must_try_dishes", "Must-Try Local Dishes"),
        ("important_places_structured", "Important Places Around Stay"),
        ("souvenir_guide", "Souvenir Shopping Guide"),
        ("cultural_etiquette", "Cultural Etiquette & Local Phrases"),
        ("packing_list", "Tailored Packing List"),
        ("safety_contacts", "Safety & Emergency Contacts"),
        ("mobile_connectivity", "Mobile Connectivity Guide"),
        ("health_vaccination", "Health & Vaccination Guidance"),
        ("getting_around", "Getting Around"),
        ("thank_you_page", "Thank You Page"),
    ]

    def check(self, doc: AIGDocument) -> list[QCIssue]:
        issues: list[QCIssue] = []

        # Mandatory section presence
        for field, label in self.MANDATORY_SECTIONS:
            value = getattr(doc, field, None)
            missing = (
                value is None
                or value == ""
                or (isinstance(value, list) and len(value) == 0)
            )
            if missing:
                issues.append(QCIssue(section=label, descriptions=[f"Section '{label}' is missing or empty."]))

        # Days present
        if not doc.days:
            issues.append(QCIssue(section="Day-wise Itinerary", descriptions=["No days were generated."]))

        # Title quality (basic check without AI)
        if not doc.title or doc.title.lower().startswith("all inclusive guide"):
            issues.append(QCIssue(section="Cover Page", descriptions=["Title is generic or missing."]))

        return issues
