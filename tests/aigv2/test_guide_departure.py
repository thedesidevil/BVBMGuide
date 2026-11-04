from src.aigv2.guide.departure import departure_checklist
from src.aigv2.models import Traveller

BASE = ["Passports and travel documents", "Flight tickets and boarding passes", "Phones and chargers",
        "Any medication", "Small snacks and water for the airport", "Valuables and souvenirs"]
CHILD = "Your child's essentials"


def test_adults_only_fixed_order():
    assert departure_checklist(Traveller(adults=2), True) == BASE


def test_young_child_adds_line_before_snacks():
    items = departure_checklist(Traveller(adults=2, kids_ages=[2]), True)
    assert items == BASE[:4] + [CHILD] + BASE[4:]


def test_twelve_year_old_is_not_a_child():
    assert CHILD not in departure_checklist(Traveller(adults=2, kids_ages=[12]), True)


def test_child_counts_add_line():
    assert CHILD in departure_checklist(Traveller(adults=2, child_counts={"CWOB": 1}), True)
    assert CHILD not in departure_checklist(Traveller(adults=2, child_counts={"CWOB": 0}), True)


def test_domestic_replaces_passports():
    items = departure_checklist(Traveller(adults=2), False)
    assert items[0] == "Photo ID for the airport" and "Passports and travel documents" not in items
    assert items[1:] == BASE[1:]
