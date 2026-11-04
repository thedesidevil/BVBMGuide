"""Day-page assembler for render2: dispatches each guide component to its renderer."""
from __future__ import annotations

from src.aigv2.guide import model as M
from src.aigv2.render2 import day_components as D
from src.aigv2.render2 import meals as ML

RENDERERS = {
    M.Opener: D.render_opener,
    M.YourDay: D.render_your_day,
    M.JourneyStrip: D.render_journey_strip,
    M.SightseeingCard: D.render_sightseeing_card,
    M.SimpleCard: D.render_simple_card,
    M.BookingCard: D.render_booking_card,
    M.ChecklistCard: D.render_checklist_card,
    M.OptionCards: D.render_option_cards,
    M.MealBlock: ML.render_meal_block,
    M.PlaceholderMeal: ML.render_placeholder_meal,
    M.ReviewMarkerBlock: D.render_marker_block,
}
RENDERERS_BY_NAME = {cls.__name__: fn for cls, fn in RENDERERS.items()}


def render_day_page(doc, W: float, page: M.Page) -> None:
    """Render a day Page's components in order. The caller creates the section (frame.add_guide_section)."""
    for c in page.components:
        fn = RENDERERS.get(type(c))
        if fn is None:
            raise TypeError(f"no renderer for {type(c).__name__}")
        fn(doc, W, c)
