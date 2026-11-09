"""Day-page assembler for render2: dispatches each guide component to its renderer."""
from __future__ import annotations

from src.aigv2.guide import model as M
from src.aigv2.render2 import day_components as D
from src.aigv2.render2 import meals as ML
from src.aigv2.render2 import page_components as PC
from src.aigv2.render2 import reference_components as RC

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
    M.ReferenceOpener: RC.render_reference_opener,
    M.FactRowBlock: RC.render_fact_row,
    M.TitledParas: RC.render_titled_paras,
    M.ChecklistGroups: RC.render_checklist_groups,
    M.TipPanel: RC.render_tip_panel,
    M.NotePanel: RC.render_note_panel,
    M.AppGrid: RC.render_app_grid,
    M.PlaceGroups: RC.render_place_groups,
    M.DishGrid: RC.render_dish_grid,
    M.SouvenirGrid: RC.render_souvenir_grid,
    M.DosDonts: RC.render_dos_donts,
    M.PhraseTable: RC.render_phrase_table,
    M.EmergencyStrip: RC.render_emergency_strip,
    M.ContactCards: RC.render_contact_cards,
    M.Letter: PC.render_letter,
    M.ThankYou: PC.render_thank_you,
}
RENDERERS_BY_NAME = {cls.__name__: fn for cls, fn in RENDERERS.items()}


def render_day_page(doc, W: float, page: M.Page) -> None:
    """Render a day Page's components in order. The caller creates the section (frame.add_guide_section)."""
    for c in page.components:
        fn = RENDERERS.get(type(c))
        if fn is None:
            raise TypeError(f"no renderer for {type(c).__name__}")
        if isinstance(c, (M.ReferenceOpener, M.ThankYou)):
            fn(doc, W, c, bookmark=page.bookmark)
        else:
            fn(doc, W, c)


def render_guide2(guide: M.Guide) -> bytes:
    from src.aigv2.render2.document import render_guide2 as _render
    return _render(guide)
