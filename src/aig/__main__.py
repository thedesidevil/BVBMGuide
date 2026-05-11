"""CLI for AIG generation: parse inputs and generate guides."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule

from src.common.ai_provider import get_ai_client
from .parser import parse_itinerary

app = typer.Typer(
    name="aig",
    help="Generate All Inclusive Guides from client itineraries",
)
console = Console()


@app.command()
def parse(
    input_dir: Path = typer.Argument(
        ...,
        help="Path to the input directory or itinerary PDF",
        exists=True,
    ),
    days: bool = typer.Option(
        False,
        "--days", "-d",
        help="Also print the day-by-day activity preview",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="AI API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Parse input files and show a found/missing summary."""

    # Determine the itinerary file
    if input_dir.is_file():
        itinerary_pdf = input_dir
    else:
        pdfs = list(input_dir.glob("*.pdf"))
        if not pdfs:
            console.print(f"[red]No PDF files found in {input_dir}[/red]")
            raise typer.Exit(1)
        itinerary_pdf = pdfs[0]
        if len(pdfs) > 1:
            console.print(f"[dim]Multiple PDFs found, using: {itinerary_pdf.name}[/dim]")

    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        ai_client = None
        console.print("[dim]No AI API key — using regex parser[/dim]")

    itinerary = parse_itinerary(itinerary_pdf, ai_client=ai_client)

    console.print()
    console.print(Panel.fit("[bold]PARSED ITINERARY SUMMARY[/bold]", border_style="blue"))
    console.print()

    # FOUND section
    console.print(Rule("[green bold]  FOUND IN ITINERARY  [/green bold]", style="green"))
    console.print()

    if itinerary.destinations:
        console.print(f"  [bold]{'Destinations':<20}[/bold] {', '.join(itinerary.destinations)}")
    elif itinerary.destination and itinerary.destination != "Unknown":
        console.print(f"  [bold]{'Destinations':<20}[/bold] {itinerary.destination}")

    if itinerary.trip_start_date and itinerary.trip_end_date:
        console.print(
            f"  [bold]{'Trip Dates':<20}[/bold] "
            f"{itinerary.trip_start_date} – {itinerary.trip_end_date} "
            f"({itinerary.duration_days} days)"
        )
    elif itinerary.duration_days:
        console.print(f"  [bold]{'Duration':<20}[/bold] {itinerary.duration_days} days")

    if itinerary.hotel_stays:
        console.print(f"  [bold]{'Hotels':<20}[/bold]")
        for stay in itinerary.hotel_stays:
            dates = ""
            if stay.check_in_date and stay.check_out_date:
                dates = f" ({stay.check_in_date} – {stay.check_out_date})"
            console.print(f"  {'':20}  [cyan]{stay.city}[/cyan]: {stay.hotel_name}{dates}")
    elif itinerary.hotel_name:
        console.print(f"  [bold]{'Hotel':<20}[/bold] {itinerary.hotel_name}")

    if itinerary.client_name:
        console.print(f"  [bold]{'Client Name':<20}[/bold] {itinerary.client_name}")
    if itinerary.num_guests:
        console.print(f"  [bold]{'Guests':<20}[/bold] {itinerary.num_guests}")
    if itinerary.dietary_preferences:
        console.print(f"  [bold]{'Dietary Prefs':<20}[/bold] {', '.join(itinerary.dietary_preferences)}")
    if itinerary.food_allergies:
        console.print(f"  [bold]{'Food Allergies':<20}[/bold] {', '.join(itinerary.food_allergies)}")
    if itinerary.cuisine_preferences:
        console.print(f"  [bold]{'Cuisine Prefs':<20}[/bold] {', '.join(itinerary.cuisine_preferences)}")
    if itinerary.budget_level:
        console.print(f"  [bold]{'Budget':<20}[/bold] {itinerary.budget_level}")
    if itinerary.special_occasions:
        console.print(f"  [bold]{'Special Occasions':<20}[/bold] {', '.join(itinerary.special_occasions)}")
    if itinerary.transport_mode:
        console.print(f"  [bold]{'Transport':<20}[/bold] {itinerary.transport_mode}")
    if itinerary.days:
        console.print(f"  [bold]{'Days Extracted':<20}[/bold] {len(itinerary.days)}")

    console.print()

    # MISSING section
    missing: list[tuple[str, str]] = []

    if not itinerary.client_name:
        missing.append(("Client name", "not found in PDF"))
    if not itinerary.num_guests:
        missing.append(("Number of guests", "not specified"))
    if not itinerary.food_allergies:
        missing.append(("Food allergies", "not specified"))
    if not itinerary.cuisine_preferences:
        missing.append(("Cuisine preferences", "not specified"))
    if not itinerary.budget_level:
        missing.append(("Budget level", "not specified"))
    if not itinerary.special_occasions:
        missing.append(("Special occasions", "not specified"))

    if missing:
        console.print(
            Rule(
                "[yellow bold]  MISSING[/yellow bold]  [dim](needed for full AIG generation)[/dim]",
                style="yellow",
            )
        )
        console.print()
        for field, reason in missing:
            console.print(f"  [yellow]x[/yellow]  [bold]{field:<22}[/bold] — {reason}")
        console.print()

    # Overnight breakdown
    if itinerary.days:
        from rich.table import Table

        console.print(Rule("[bold]  OVERNIGHT BREAKDOWN  [/bold]", style="blue"))
        console.print()

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Day", style="bold cyan", no_wrap=True)
        table.add_column("Date", no_wrap=True)
        table.add_column("City", no_wrap=True)
        table.add_column("Hotel")

        for day in itinerary.days:
            date_str = day.date or ""
            city = day.overnight_city or "[dim]—[/dim]"
            hotel = day.overnight_hotel or "[dim]—[/dim]"

            if day.overnight_city == "Departure day":
                city = "[dim]Departure[/dim]"
                hotel = "[dim]no overnight[/dim]"
            elif day.overnight_city == "On Cruise":
                city = "[blue]On Cruise[/blue]"
                hotel = "[dim]—[/dim]"

            table.add_row(f"Day {day.day_number}", date_str, city, hotel)

        console.print(table)
        console.print()

    # Activity detail
    if days and itinerary.days:
        console.print(Rule("[dim]  ACTIVITIES  [/dim]", style="dim"))
        console.print()
        for day in itinerary.days:
            console.print(f"  [bold cyan]Day {day.day_number}[/bold cyan] [{day.date or ''}]: {day.title}")
            for act in day.activities[:4]:
                marker = "o" if act.is_optional else "."
                cost = " [dim](extra cost)[/dim]" if act.extra_cost else ""
                console.print(f"    [dim]{marker}[/dim] {act.name}{cost}")
            if len(day.activities) > 4:
                console.print(f"    [dim]... and {len(day.activities) - 4} more[/dim]")
            console.print()


@app.command()
def generate(
    input_dir: Path = typer.Argument(
        ...,
        help="Path to the input directory or itinerary PDF",
        exists=True,
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: auto-generated)",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Generate an All Inclusive Guide from input files.

    Input can be a directory containing itinerary PDF, booking confirmations,
    and flight details, or a single itinerary PDF file.
    """

    console.print(Panel.fit(
        "[bold blue]AIG Generator[/bold blue]\n"
        "[dim]Bon Voyage by Marina[/dim]",
        border_style="blue",
    ))

    # Determine the itinerary file
    if input_dir.is_file():
        itinerary_pdf = input_dir
    else:
        pdfs = list(input_dir.glob("*.pdf"))
        if not pdfs:
            console.print(f"[red]No PDF files found in {input_dir}[/red]")
            raise typer.Exit(1)
        itinerary_pdf = pdfs[0]
        if len(pdfs) > 1:
            console.print(f"[dim]Multiple PDFs found, using: {itinerary_pdf.name}[/dim]")

    # Step 1: Parse
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Parsing itinerary...", total=None)
        try:
            ai_client = get_ai_client(api_key=api_key)
        except ValueError:
            ai_client = None
        itinerary = parse_itinerary(itinerary_pdf, ai_client=ai_client)
        progress.update(task, completed=True)

    console.print("[green]Parsed.[/green]")

    # Step 2: Validate — show found/missing
    from .validator import validate_and_confirm
    if not validate_and_confirm(itinerary, console):
        console.print("\n[yellow]Aborted.[/yellow] Update your input files and re-run.")
        raise typer.Exit(0)

    # Step 3: Generate sections (not yet implemented)
    console.print("\n[yellow]Section generation not yet implemented.[/yellow]")
    console.print("[dim]Sections will be built incrementally in future sessions.[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
