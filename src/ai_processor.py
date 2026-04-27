"""AI processor — food preference parsing and restaurant ranking."""

import json
from typing import Optional

from .models import FoodPreferences, Restaurant, DiningStyle
from .ai_provider import AIClient, get_ai_client


class AIProcessor:
    """Uses AI to parse food preferences and rank restaurants."""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.client = get_ai_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    def parse_food_preferences(self, raw_input: str) -> FoodPreferences:
        """Parse free-text food preferences into structured data."""
        if not raw_input.strip():
            return FoodPreferences(raw_input=raw_input)

        prompt = f"""Parse the following food preferences into structured data.

User input: "{raw_input}"

Return a JSON object with these fields:
- dietary_restrictions: list (e.g., "vegetarian", "vegan", "no pork", "no beef", "pescatarian")
- allergies: list (e.g., "nuts", "shellfish", "gluten", "dairy")
- cuisine_preferences: list (e.g., "local", "seafood", "Italian", "spicy", "Asian")
- cuisine_dislikes: list of cuisines to avoid
- dining_styles: list from ["casual", "fine_dining", "street_food", "cafe", "family_friendly", "romantic"]
- budget_level: one of "budget", "mid-range", "luxury", or null
- special_occasions: list (e.g., "anniversary", "birthday", "honeymoon")
- party_composition: list (e.g., "couple", "family", "with kids", "solo", "group")

Only include fields clearly mentioned or implied. Return ONLY the JSON object."""

        result_text = self.client.complete(prompt, max_tokens=1024)

        try:
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()
            parsed = json.loads(result_text)

            dining_styles = []
            for style in parsed.get("dining_styles", []):
                try:
                    dining_styles.append(DiningStyle(style))
                except ValueError:
                    pass

            return FoodPreferences(
                dietary_restrictions=parsed.get("dietary_restrictions", []),
                allergies=parsed.get("allergies", []),
                cuisine_preferences=parsed.get("cuisine_preferences", []),
                cuisine_dislikes=parsed.get("cuisine_dislikes", []),
                dining_styles=dining_styles,
                budget_level=parsed.get("budget_level"),
                special_occasions=parsed.get("special_occasions", []),
                party_composition=parsed.get("party_composition", []),
                raw_input=raw_input,
            )
        except (json.JSONDecodeError, KeyError, IndexError):
            return FoodPreferences(raw_input=raw_input)

    def rank_restaurants_for_preferences(
        self,
        restaurants: list[Restaurant],
        preferences: FoodPreferences,
    ) -> list[Restaurant]:
        """Use AI to rank restaurants by how well they match preferences."""
        if not restaurants or not preferences.raw_input:
            return restaurants

        summaries = [
            {
                "index": i,
                "name": r.name,
                "cuisine": r.cuisine_type,
                "vegetarian_friendly": r.vegetarian_friendly,
                "best_for": r.best_for,
            }
            for i, r in enumerate(restaurants)
        ]

        prompt = f"""Given these food preferences:
"{preferences.raw_input}"

Dietary restrictions: {preferences.dietary_restrictions}
Allergies: {preferences.allergies}
Cuisine preferences: {preferences.cuisine_preferences}

Rank these restaurants from most to least suitable:
{json.dumps(summaries, indent=2)}

Return a JSON array of indices in order of preference (best first).
CRITICAL: Exclude restaurants conflicting with dietary restrictions or allergies.
Return ONLY the JSON array, e.g., [2, 0, 4, 1, 3]"""

        try:
            result_text = self.client.complete(prompt, max_tokens=256)
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            indices = json.loads(result_text.strip())

            ranked = [restaurants[idx] for idx in indices if 0 <= idx < len(restaurants)]
            for r in restaurants:
                if r not in ranked:
                    ranked.append(r)
            return ranked
        except (json.JSONDecodeError, IndexError):
            return restaurants
