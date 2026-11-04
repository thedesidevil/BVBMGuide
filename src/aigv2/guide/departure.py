"""Fixed departure-day check-out checklist (no AI, no network)."""
from src.aigv2.models import Traveller

_CHILD_UNDER = 12


def has_child(travellers: Traveller) -> bool:
    return any(a < _CHILD_UNDER for a in travellers.kids_ages) or any(n > 0 for n in travellers.child_counts.values())


def departure_checklist(travellers: Traveller, international: bool) -> list[str]:
    items = ["Passports and travel documents" if international else "Photo ID for the airport",
             "Flight tickets and boarding passes", "Phones and chargers", "Any medication"]
    if has_child(travellers):
        items.append("Your child's essentials")
    return items + ["Small snacks and water for the airport", "Valuables and souvenirs"]
