"""Command-line interface for the AIG Generator."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .pdf_parser import parse_itinerary
from .user_input import collect_user_inputs
from .ai_processor import AIProcessor
from .generator import AIGGenerator
from .ai_provider import get_ai_client
from .library_builder import LibraryBuilder, LibraryDatabase
from .models import Restaurant

app = typer.Typer(
    name="aig-generator",
    help="Generate All Inclusive Guides from client itineraries"
)
console = Console()


@app.command()
def generate(
    itinerary_pdf: Path = typer.Argument(
        ...,
        help="Path to the client itinerary PDF",
        exists=True
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: auto-generated)"
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses ANTHROPIC_API_KEY or OPENAI_API_KEY from env)"
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider", "-p",
        help="AI provider: 'openai' or 'anthropic' (auto-detected from env)"
    )
):
    """Generate an All Inclusive Guide from a client itinerary."""
    
    console.print(Panel.fit(
        "[bold blue]🌍 AIG Generator[/bold blue]\n"
        "[dim]Bon Voyage by Marina[/dim]",
        border_style="blue"
    ))
    
    # Step 1: Parse the itinerary PDF
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing itinerary PDF...", total=None)
        itinerary = parse_itinerary(itinerary_pdf)
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Itinerary parsed successfully\n")
    
    # Step 2: Collect user inputs
    user_inputs = collect_user_inputs(itinerary)
    
    # Step 3: Initialize AI clients
    try:
        ai = AIProcessor(provider=provider, api_key=api_key)
        ai_client = get_ai_client(provider=provider, api_key=api_key)
        console.print(f"[dim]Using AI: {ai.client}[/dim]")
    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        console.print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
        raise typer.Exit(1)

    # Step 4: Parse food preferences
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Analyzing food preferences...", total=None)
        parsed_prefs = ai.parse_food_preferences(user_inputs.food_preferences.raw_input)
        user_inputs.food_preferences = parsed_prefs
        progress.update(task, completed=True)

    console.print("[green]✓[/green] Food preferences analyzed")
    if parsed_prefs.dietary_restrictions:
        console.print(f"  [dim]Dietary:[/dim] {', '.join(parsed_prefs.dietary_restrictions)}")
    if parsed_prefs.allergies:
        console.print(f"  [dim]Allergies:[/dim] {', '.join(parsed_prefs.allergies)}")

    # Step 5: Load restaurants from library
    db_path = library_path / "library_db.json"
    restaurants: list[Restaurant] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Loading restaurants from library...", total=None)
        if db_path.exists():
            db = LibraryDatabase(db_path)
            for r in db.get_restaurants(itinerary.destination):
                restaurants.append(Restaurant(
                    name=r.get("name", "Unknown"),
                    location=itinerary.destination,
                    cuisine_type=r.get("cuisine_type", []),
                    price_range=r.get("price_range"),
                    ambience=r.get("ambience"),
                    must_try_dishes=r.get("must_try_dishes", []),
                    hours=r.get("hours"),
                    google_maps_link=r.get("google_maps_link"),
                    distance_from_hotel=r.get("distance_from_hotel"),
                    best_for=r.get("best_for", []),
                    vegetarian_friendly=r.get("vegetarian_friendly", False),
                ))
            console.print(f"[green]✓[/green] Loaded {len(restaurants)} restaurants from library")
        else:
            console.print("[yellow]Warning:[/yellow] Library database not found. Generator will curate restaurants with AI.")
        progress.update(task, completed=True)

    # Step 6: Rank restaurants by preferences
    if restaurants:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("Ranking restaurants by preferences...", total=None)
            restaurants = ai.rank_restaurants_for_preferences(restaurants, parsed_prefs)
            progress.update(task, completed=True)
        console.print("[green]✓[/green] Restaurants ranked")

    # Step 7: Generate AIG (QC loop is built into the generator)
    generator = AIGGenerator(
        user_inputs=user_inputs,
        restaurants=restaurants,
        client=ai_client,
    )
    aig_doc = generator.generate()

    # Step 8: Save output
    if output is None:
        client_name = "_".join(user_inputs.client_names) if user_inputs.client_names else "Client"
        output = Path(f"All_Inclusive_Guide_{itinerary.destination}_{client_name}.docx")

    generator.save_docx(aig_doc, output)

    if aig_doc.unresolved_qc_issues:
        console.print(f"\n[yellow]⚠ {len(aig_doc.unresolved_qc_issues)} unresolved QC issue(s) appended to the document for human review.[/yellow]")


@app.command()
def parse(
    itinerary_pdf: Path = typer.Argument(
        ...,
        help="Path to the client itinerary PDF",
        exists=True
    ),
    days: bool = typer.Option(
        False,
        "--days", "-d",
        help="Also print the day-by-day activity preview"
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="AI API key (uses AI_API_KEY from .env if not set)"
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider", "-p",
        help="AI provider (auto-detected from env)"
    ),
):
    """Parse an itinerary PDF and show a found/missing summary."""
    from rich.rule import Rule

    try:
        ai_client = get_ai_client(api_key=api_key)
    except ValueError:
        ai_client = None
        console.print("[dim]No AI API key — using regex parser[/dim]")

    itinerary = parse_itinerary(itinerary_pdf, ai_client=ai_client)

    console.print()
    console.print(Panel.fit("[bold]PARSED ITINERARY SUMMARY[/bold]", border_style="blue"))
    console.print()

    # ---- FOUND section ----
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
            console.print(f"  {'':20}  [cyan]·[/cyan] [cyan]{stay.city}[/cyan]: {stay.hotel_name}{dates}")
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

    # ---- MISSING section ----
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
            console.print(f"  [yellow]✗[/yellow]  [bold]{field:<22}[/bold] — {reason}")
        console.print()

    # ---- Overnight breakdown (always shown) ----
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

    # ---- Optional activity detail ----
    if days and itinerary.days:
        console.print(Rule("[dim]  ACTIVITIES  [/dim]", style="dim"))
        console.print()
        for day in itinerary.days:
            console.print(f"  [bold cyan]Day {day.day_number}[/bold cyan] [{day.date or ''}]: {day.title}")
            for act in day.activities[:4]:
                marker = "○" if act.is_optional else "·"
                cost = " [dim](extra cost)[/dim]" if act.extra_cost else ""
                console.print(f"    [dim]{marker}[/dim] {act.name}{cost}")
            if len(day.activities) > 4:
                console.print(f"    [dim]… and {len(day.activities) - 4} more[/dim]")
            console.print()


@app.command()
def list_restaurants(
    destination: str = typer.Argument(..., help="Destination to search for"),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    )
):
    """List all restaurants in the library for a destination."""

    db_path = library_path / "library_db.json"
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)

    db = LibraryDatabase(db_path)
    restaurants = db.get_restaurants(destination)

    console.print(f"\n[bold]Found {len(restaurants)} restaurants for {destination}:[/bold]")
    console.print("[dim](from pre-built database)[/dim]\n")

    for r in restaurants:
        console.print(f"[cyan]{r.get('name', 'Unknown')}[/cyan]")
        if r.get('cuisine_type'):
            console.print(f"  [dim]Cuisine:[/dim] {', '.join(r['cuisine_type'])}")
        if r.get('must_try_dishes'):
            console.print(f"  [dim]Must-try:[/dim] {', '.join(r['must_try_dishes'][:3])}")
        if r.get('price_range'):
            console.print(f"  [dim]Price:[/dim] {r['price_range']}")
        if r.get('hours'):
            console.print(f"  [dim]Hours:[/dim] {r['hours']}")
        if r.get('ambience'):
            console.print(f"  [dim]Ambience:[/dim] {r['ambience'][:60]}...")
        console.print()


@app.command()
def build_library(
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force re-processing of all files (ignore cache)"
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses ANTHROPIC_API_KEY or OPENAI_API_KEY from env)"
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider", "-p",
        help="AI provider: 'openai' or 'anthropic' (auto-detected from env)"
    )
):
    """Build the library database using AI extraction.
    
    This processes all DOCX and PDF files in the library and creates a structured
    JSON database for fast querying. Supports incremental builds - only new or
    modified files are processed unless --force is used.
    """
    
    console.print(Panel.fit(
        "[bold blue]📚 Library Database Builder[/bold blue]\n"
        "[dim]Using AI to extract structured data from all guides[/dim]",
        border_style="blue"
    ))
    
    if force:
        console.print("[yellow]Force mode: Re-processing all files[/yellow]\n")
    
    try:
        builder = LibraryBuilder(library_path, provider=provider, api_key=api_key)
        console.print(f"[dim]Using AI: {builder.client}[/dim]\n")
        builder.build_database(force=force)
    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        console.print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def library_stats(
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    )
):
    """Show statistics about the library database."""
    
    db_path = library_path / "library_db.json"
    
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)
    
    db = LibraryDatabase(db_path)
    
    console.print(Panel.fit(
        "[bold]📊 Library Database Statistics[/bold]",
        border_style="blue"
    ))
    
    processed_files = db.data.get('_processed_files', {})
    
    console.print(f"\n[dim]Database version:[/dim] {db.data.get('version', 'Unknown')}")
    console.print(f"[dim]Built at:[/dim] {db.data.get('built_at', 'Unknown')}")
    console.print(f"[dim]Files processed:[/dim] {len(processed_files)}")
    console.print(f"\n[bold]Destinations:[/bold] {len(db.get_destinations())}\n")
    
    from rich.table import Table
    table = Table(show_header=True)
    table.add_column("Destination", style="cyan")
    table.add_column("Restaurants", justify="right")
    table.add_column("Attractions", justify="right")
    table.add_column("Local Dishes", justify="right")
    table.add_column("Phrases", justify="right")
    
    for dest in sorted(db.get_destinations()):
        data = db.data["destinations"][dest]
        table.add_row(
            dest,
            str(len(data.get("restaurants", []))),
            str(len(data.get("attractions", []))),
            str(len(data.get("local_dishes", []))),
            str(len(data.get("phrases", [])))
        )
    
    console.print(table)


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()

