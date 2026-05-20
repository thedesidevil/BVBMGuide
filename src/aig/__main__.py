"""CLI for AIG generation: parse inputs and generate guides."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule

from src.common.ai_provider import get_ai_client
from src.common.models import TripFacts
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
        help="Path to the input directory (multi-file) or a single itinerary PDF",
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
    """Parse input files and show a found/missing summary.

    When given a directory, all PDF and DOCX files are parsed and facts are
    saved to trip_facts.json inside that directory.
    When given a single file, the existing single-file parser runs (unchanged).
    """
    if input_dir.is_dir():
        _parse_folder(input_dir, show_days=days, api_key=api_key)
    else:
        _parse_single_file(input_dir, show_days=days, api_key=api_key)


def _parse_folder(folder: Path, show_days: bool, api_key: Optional[str]) -> None:
    from .folder_parser import FolderParser

    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        console.print("[red]AI API key required for multi-file parsing. Set AI_API_KEY in .env[/red]")
        raise typer.Exit(1)

    supported = sorted(f for f in folder.iterdir() if f.suffix.lower() in {".pdf", ".docx"})
    if not supported:
        console.print(f"[red]No PDF or DOCX files found in {folder}[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(f"Scanning {folder}/ — {len(supported)} file(s) found")
    for f in supported:
        console.print(f"  [dim]✓ {f.name}[/dim]")
    console.print()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Extracting facts with AI...", total=None)
        parser = FolderParser(ai_client=ai_client)
        facts, warnings = parser.parse(folder)
        progress.update(task, completed=True)

    for w in warnings:
        console.print(f"  [yellow]⚠ Could not extract text from {w} — skipped[/yellow]")

    _print_trip_facts_summary(facts)

    if show_days and facts.days:
        console.print(Rule("[dim]  ACTIVITIES  [/dim]", style="dim"))
        console.print()
        for day in facts.days:
            console.print(f"  [bold cyan]Day {day.day_number}[/bold cyan] [{day.date or ''}]: {day.title or ''}")
            for act in day.activities[:4]:
                console.print(f"    [dim]·[/dim] {act}")
            if len(day.activities) > 4:
                console.print(f"    [dim]... and {len(day.activities) - 4} more[/dim]")
            console.print()

    out_path = folder / "trip_facts.json"
    out_path.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\n[green]Saved →[/green] {out_path}")


def _print_trip_facts_summary(facts: TripFacts) -> None:
    console.print(Rule("[green bold]  FOUND  [/green bold]", style="green"))
    console.print()
    if facts.client_names:
        console.print(f"  [bold]{'client_names':<22}[/bold] {', '.join(facts.client_names)}")
    if facts.num_guests:
        console.print(f"  [bold]{'num_guests':<22}[/bold] {facts.num_guests}")
    if facts.departure_city:
        console.print(f"  [bold]{'departure_city':<22}[/bold] {facts.departure_city}")
    if facts.destinations:
        console.print(f"  [bold]{'destinations':<22}[/bold] {' → '.join(facts.destinations)}")
    if facts.trip_start_date:
        console.print(f"  [bold]{'trip_start_date':<22}[/bold] {facts.trip_start_date}")
    if facts.trip_end_date:
        console.print(f"  [bold]{'trip_end_date':<22}[/bold] {facts.trip_end_date}")
    if facts.days:
        console.print(f"  [bold]{'days':<22}[/bold] {len(facts.days)} days extracted")
    if facts.hotels:
        console.print(f"  [bold]{'hotels':<22}[/bold] {len(facts.hotels)} properties")
    if facts.transport_modes:
        console.print(f"  [bold]{'transport_modes':<22}[/bold] {len(facts.transport_modes)} legs")
    if facts.dietary_restrictions:
        console.print(f"  [bold]{'dietary_restrictions':<22}[/bold] {', '.join(facts.dietary_restrictions)}")
    if facts.food_allergies:
        console.print(f"  [bold]{'food_allergies':<22}[/bold] {', '.join(facts.food_allergies)}")
    if facts.cuisine_preferences:
        console.print(f"  [bold]{'cuisine_preferences':<22}[/bold] {', '.join(facts.cuisine_preferences)}")

    all_fields = [
        "client_names", "num_guests", "departure_city", "destinations",
        "trip_start_date", "trip_end_date", "days", "hotels",
        "transport_modes", "dietary_restrictions", "food_allergies", "cuisine_preferences",
    ]
    required = facts.missing_required()
    optional_missing = [
        f for f in all_fields
        if not getattr(facts, f) and f not in required
    ]

    if required or optional_missing:
        console.print()
        console.print(Rule("[yellow bold]  MISSING  [/yellow bold]", style="yellow"))
        console.print()
        for field in required:
            console.print(f"  [red]✗[/red]  [bold]{field:<26}[/bold] [red](required for generation)[/red]")
        for field in optional_missing:
            console.print(f"  [yellow]·[/yellow]  [bold]{field:<26}[/bold] [dim](optional — saved as null/[])[/dim]")
    console.print()


def _parse_single_file(file: Path, show_days: bool, api_key: Optional[str]) -> None:
    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        ai_client = None
        console.print("[dim]No AI API key — using regex parser[/dim]")

    itinerary = parse_itinerary(file, ai_client=ai_client)

    console.print()
    console.print(Panel.fit("[bold]PARSED ITINERARY SUMMARY[/bold]", border_style="blue"))
    console.print()

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

    if show_days and itinerary.days:
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
        help="Path to the input directory containing trip_facts.json",
        exists=True,
        file_okay=False,
    ),
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
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
    """Generate an All Inclusive Guide from trip_facts.json.

    Run 'parse <input_dir>' first to extract and save trip facts.
    """
    console.print(Panel.fit(
        "[bold blue]AIG Generator[/bold blue]\n"
        "[dim]Bon Voyage by Marina[/dim]",
        border_style="blue",
    ))

    if input_dir.is_file():
        console.print("[red]generate requires a directory, not a file.[/red]")
        raise typer.Exit(1)

    facts_path = input_dir / "trip_facts.json"
    if not facts_path.exists():
        console.print(
            f"[red]trip_facts.json not found in {input_dir}[/red]\n"
            f"Run [bold]python -m src.aig parse {input_dir}[/bold] first."
        )
        raise typer.Exit(1)

    facts = TripFacts.model_validate_json(facts_path.read_text(encoding="utf-8"))

    _print_trip_facts_summary(facts)

    missing = facts.missing_required()
    if missing:
        console.print(
            f"[red]Cannot generate: required fields are missing:[/red] {', '.join(missing)}\n"
            f"Edit [bold]{facts_path}[/bold] and fill them in."
        )
        raise typer.Exit(1)

    confirmed = typer.confirm("Proceed with generation?")
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    console.print("\n[yellow]Section generation not yet implemented.[/yellow]")
    console.print("[dim]Sections will be built incrementally in future sessions.[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
