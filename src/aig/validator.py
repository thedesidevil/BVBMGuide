"""Validate parsed input completeness and present go/abort decision."""

from rich.console import Console
from rich.rule import Rule

from src.common.models import ItineraryData


def validate_and_confirm(itinerary: ItineraryData, console: Console) -> bool:
    """Show found/missing summary and ask user to proceed or abort.

    Returns True if user wants to proceed, False to abort.
    """
    missing: list[str] = []

    if not itinerary.client_name:
        missing.append("Client name")
    if not itinerary.destinations and itinerary.destination == "Unknown":
        missing.append("Destinations")
    if not itinerary.hotel_stays and not itinerary.hotel_name:
        missing.append("Hotel information")
    if not itinerary.days:
        missing.append("Day-by-day itinerary")
    if not itinerary.trip_start_date:
        missing.append("Trip start date")

    if not missing:
        console.print("\n[green]All required fields found.[/green]")
        return True

    console.print()
    console.print(Rule("[yellow bold]  MISSING REQUIRED FIELDS  [/yellow bold]", style="yellow"))
    console.print()
    for field in missing:
        console.print(f"  [yellow]x[/yellow] {field}")
    console.print()

    answer = console.input("[bold]Proceed anyway? [y/N]: [/bold]").strip().lower()
    return answer in ("y", "yes")
