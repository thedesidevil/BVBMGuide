"""User input collection for missing itinerary information."""

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table

from .models import ItineraryData, UserInputs, FoodPreferences


console = Console()


class UserInputCollector:
    """Collects missing information from the user interactively."""
    
    def __init__(self, itinerary: ItineraryData):
        self.itinerary = itinerary
    
    def collect(self) -> UserInputs:
        """Collect all required inputs from user."""
        self._display_extracted_info()
        
        # Collect missing information
        hotel_name = self._collect_hotel()
        client_names = self._collect_client_names()
        trip_dates = self._collect_trip_dates()
        food_preferences = self._collect_food_preferences()
        additional_notes = self._collect_additional_notes()
        
        return UserInputs(
            itinerary=self.itinerary,
            hotel_name=hotel_name,
            food_preferences=food_preferences,
            client_names=client_names,
            trip_dates=trip_dates,
            additional_notes=additional_notes
        )
    
    def _display_extracted_info(self) -> None:
        """Display what was extracted from the PDF."""
        console.print("\n")
        console.print(Panel.fit(
            f"[bold green]✓ Itinerary Parsed Successfully[/bold green]\n\n"
            f"[bold]Destination:[/bold] {self.itinerary.destination}\n"
            f"[bold]Duration:[/bold] {self.itinerary.duration_days} days\n"
            f"[bold]Title:[/bold] {self.itinerary.trip_title or 'Not detected'}",
            title="📄 Extracted Information"
        ))
        
        # Show days overview
        if self.itinerary.days:
            table = Table(title="Day-by-Day Overview", show_header=True)
            table.add_column("Day", style="cyan", width=6)
            table.add_column("Title", style="white")
            table.add_column("Activities", style="dim")
            
            for day in self.itinerary.days:
                activity_count = len(day.activities)
                table.add_row(
                    str(day.day_number),
                    day.title,
                    f"{activity_count} activities"
                )
            
            console.print(table)
        console.print("\n")
    
    def _collect_hotel(self) -> str:
        """Collect hotel name from user."""
        console.print("[bold yellow]🏨 Hotel Information[/bold yellow]")
        
        if self.itinerary.hotel_name:
            use_existing = Confirm.ask(
                f"  Hotel detected: [cyan]{self.itinerary.hotel_name}[/cyan]. Use this?",
                default=True
            )
            if use_existing:
                return self.itinerary.hotel_name
        
        hotel = Prompt.ask("  Enter the hotel name")
        return hotel.strip()
    
    def _collect_client_names(self) -> list[str]:
        """Collect client names."""
        console.print("\n[bold yellow]👤 Client Information[/bold yellow]")
        
        if self.itinerary.client_name:
            console.print(f"  Detected from filename: [cyan]{self.itinerary.client_name}[/cyan]")
        
        names_input = Prompt.ask(
            "  Enter client name(s) [dim](comma-separated for multiple)[/dim]",
            default=self.itinerary.client_name or ""
        )
        
        names = [n.strip() for n in names_input.split(',') if n.strip()]
        return names
    
    def _collect_trip_dates(self) -> str | None:
        """Collect trip dates."""
        console.print("\n[bold yellow]📅 Trip Dates[/bold yellow]")
        
        dates = Prompt.ask(
            "  Enter trip dates [dim](e.g., Dec 28 - Jan 2, 2025)[/dim]",
            default=""
        )
        
        return dates.strip() if dates.strip() else None
    
    def _collect_food_preferences(self) -> FoodPreferences:
        """Collect food preferences as free text."""
        console.print("\n[bold yellow]🍽️  Food Preferences[/bold yellow]")
        console.print("  [dim]Describe food preferences naturally. Examples:[/dim]")
        console.print("  [dim]  • 'Vegetarian, no eggs, loves spicy food'[/dim]")
        console.print("  [dim]  • 'Allergic to nuts, prefers local cuisine'[/dim]")
        console.print("  [dim]  • 'Looking for romantic dinner spots, fine dining for anniversary'[/dim]")
        console.print("  [dim]  • 'Family with kids, need child-friendly restaurants'[/dim]")
        console.print("")
        
        raw_input = Prompt.ask("  Enter food preferences")
        
        # For now, store raw input - AI will parse later
        return FoodPreferences(raw_input=raw_input.strip())
    
    def _collect_additional_notes(self) -> str | None:
        """Collect any additional notes."""
        console.print("\n[bold yellow]📝 Additional Notes[/bold yellow]")
        
        notes = Prompt.ask(
            "  Any other preferences or requirements? [dim](press Enter to skip)[/dim]",
            default=""
        )
        
        return notes.strip() if notes.strip() else None


def collect_user_inputs(itinerary: ItineraryData) -> UserInputs:
    """Convenience function to collect user inputs."""
    collector = UserInputCollector(itinerary)
    return collector.collect()

