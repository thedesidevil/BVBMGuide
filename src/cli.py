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
from .library import LibraryBuilder, LibraryDatabase, LibraryIngester, LibraryQC
from .maps import maps_url
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
    db_path = library_path / "library_db"
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
                    google_maps_link=maps_url(r["name"], itinerary.destination),
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
    workers: int = typer.Option(
        5,
        "--workers", "-w",
        help="Number of parallel AI extraction workers",
        min=1,
        max=20,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output database path — directory for sharded format (default: <library>/library_db), or a .json file for legacy flat format",
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
        builder = LibraryBuilder(library_path, provider=provider, api_key=api_key, workers=workers)
        console.print(f"[dim]Using AI: {builder.client}[/dim]\n")
        builder.build_database(force=force, output_path=output)
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
    
    db_path = library_path / "library_db"

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


@app.command()
def inspect(
    file_path: Path = typer.Argument(
        ...,
        help="Path to the AIG file to inspect (DOCX or PDF)",
        exists=True,
    ),
    field: Optional[str] = typer.Option(
        None,
        "--field", "-f",
        help="Show only this field (restaurants, attractions, hotels, local_dishes, phrases, safety_tips, covered_cities)",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from env if not set)",
    ),
):
    """Re-extract and display data from a single AIG file for spot-checking.

    Runs the same AI extraction used by build-library and pretty-prints the
    result. Does not modify the database.
    """
    builder = None
    try:
        builder = LibraryBuilder(Path("aig-library"), api_key=api_key)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"\n[dim]Extracting from:[/dim] {file_path}\n")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Running AI extraction...", total=None)
        data = builder._process_file(file_path)
        progress.update(task, completed=True)

    if data is None:
        console.print("[red]Extraction failed or returned no data.[/red]")
        raise typer.Exit(1)

    # Annotate each item with its source file (mirrors what build_database does during merge)
    src = str(file_path)
    for section in ("restaurants", "attractions", "hotels", "local_dishes"):
        for item in data.get(section) or []:
            if isinstance(item, dict):
                item["source_files"] = [src]

    output = {field: data[field] for field in [field] if field and field in data} if field else data
    import json as _json
    print(_json.dumps(output, indent=2, ensure_ascii=False))


@app.command()
def ingest(
    input_path: Path = typer.Option(
        ...,
        "--input", "-i",
        help="Folder containing AIG files to classify and move into the library",
        exists=True,
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses ANTHROPIC_API_KEY or OPENAI_API_KEY from env)"
    ),
):
    """Classify and move AIG files from --input into the correct library subfolder.

    Uses AI to determine the right destination folder for each file (creating new
    folders if needed), then moves the file. Run build-library afterwards to update
    the database.
    """
    console.print(Panel.fit(
        "[bold blue]Library Ingester[/bold blue]\n"
        "[dim]Classifying and moving AIGs into the library[/dim]",
        border_style="blue"
    ))

    try:
        ingester = LibraryIngester(library_path, api_key=api_key)
    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        console.print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
        raise typer.Exit(1)

    try:
        count = ingester.ingest(input_path)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if count:
        console.print(f"\n[bold green]✓ {count} file(s) moved.[/bold green]")
        console.print("[dim]Run 'build-library' to update the database.[/dim]")
    else:
        console.print("\n[dim]Nothing to ingest.[/dim]")


@app.command()
def library_qc(
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
    verify_sources: bool = typer.Option(
        False,
        "--verify-sources", "-v",
        help="Enable source document verification (checks if restaurants exist in source files)"
    ),
    sample_size: int = typer.Option(
        3,
        "--sample", "-n",
        help="Restaurants to verify per destination (with --verify-sources)"
    ),
    max_dests: int = typer.Option(
        20,
        "--max-dests",
        help="Maximum destinations to sample for source verification"
    ),
    spot_check: bool = typer.Option(
        False,
        "--spot-check",
        help="Print sampled unique values per attribute for manual review"
    ),
    spot_count: int = typer.Option(
        50,
        "--spot-count",
        help="Number of unique values to sample per attribute in spot-check mode"
    ),
    severity: str = typer.Option(
        "warning",
        "--severity", "-s",
        help="Minimum severity to display: critical, warning, or info"
    ),
    output_json: Optional[Path] = typer.Option(
        None,
        "--json",
        help="Save full report as JSON file"
    ),
):
    """Run comprehensive quality checks on the library database.

    Performs structural validation (missing fields, duplicates, contamination,
    outliers, file accounting) and optionally verifies entries against source
    documents. Use --spot-check for manual review of sampled attribute values.
    """
    from .library.qc import print_report, print_spot_check

    db_path = library_path / "library_db"
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)

    qc = LibraryQC(db_path, library_path)

    if spot_check:
        console.print(Panel.fit(
            "[bold]Library Spot Check[/bold]\n"
            f"[dim]Sampling {spot_count} unique values per attribute[/dim]",
            border_style="blue",
        ))
        samples = qc.spot_check(sample_count=spot_count)
        print_spot_check(samples)
        return

    console.print(Panel.fit(
        "[bold blue]Library QC[/bold blue]\n"
        "[dim]Running structural checks" +
        (" + source verification" if verify_sources else "") + "[/dim]",
        border_style="blue",
    ))

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Running quality checks...", total=None)
        report = qc.run(
            verify_sources=verify_sources,
            sample_size=sample_size,
            max_destinations=max_dests,
        )
        progress.update(task, completed=True)

    print_report(report, min_severity=severity)

    if output_json:
        with open(output_json, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
        console.print(f"[dim]Report saved to {output_json}[/dim]")

    if report.health_score < 50:
        raise typer.Exit(1)


@app.command()
def library_clean(
    dump: Optional[Path] = typer.Option(
        None,
        "--dump",
        help="Dump contaminated entries to a TSV file for review"
    ),
    apply: Optional[Path] = typer.Option(
        None,
        "--apply",
        help="Apply a reviewed TSV file to remove contaminated entries from the database"
    ),
    dump_dupes: Optional[Path] = typer.Option(
        None,
        "--dump-dupes",
        help="Dump near-duplicate restaurant pairs to a TSV for review"
    ),
    apply_dedup: Optional[Path] = typer.Option(
        None,
        "--apply-dedup",
        help="Apply a reviewed duplicates TSV to merge/remove entries"
    ),
    fix_city_variants: bool = typer.Option(
        False,
        "--fix-city-variants",
        help="Deduplicate city name variants in the coverage index"
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
):
    """Clean contaminated or duplicate entries from the library database.

    Contamination workflow:
      1. --dump: Writes contaminated highlights/area values to a TSV
      2. User reviews TSV, deletes rows they want to KEEP
      3. --apply: Removes remaining rows from the shard JSON files

    Duplicate workflow:
      1. --dump-dupes: Writes near-duplicate pairs to a TSV (keep/remove columns)
      2. User reviews: swap keep/remove if needed, delete false positive rows
      3. --apply-dedup: Merges and removes duplicate entries
    """
    from .library.qc import dump_contamination, apply_cleanup, dump_duplicates, apply_dedup as _apply_dedup, dedup_city_coverage

    db_path = library_path / "library_db"
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)

    if not any([dump, apply, dump_dupes, apply_dedup, fix_city_variants]):
        console.print("[red]Provide one of: --dump, --apply, --dump-dupes, --apply-dedup, --fix-city-variants[/red]")
        raise typer.Exit(1)

    if dump:
        count = dump_contamination(db_path, dump)
        console.print(f"[green]Wrote {count} contaminated entries to {dump}[/green]")
        console.print("[dim]Review the file, delete rows you want to KEEP, then run --apply.[/dim]")

    if apply:
        if not apply.exists():
            console.print(f"[red]File not found: {apply}[/red]")
            raise typer.Exit(1)
        removed, shards = apply_cleanup(db_path, apply)
        console.print(f"[green]Removed {removed} values from {shards} shard files.[/green]")

    if dump_dupes:
        count = dump_duplicates(db_path, dump_dupes)
        console.print(f"[green]Wrote {count} duplicate pairs to {dump_dupes}[/green]")
        console.print("[dim]Review: swap keep/remove columns if needed, delete false positive rows, then run --apply-dedup.[/dim]")

    if apply_dedup:
        if not apply_dedup.exists():
            console.print(f"[red]File not found: {apply_dedup}[/red]")
            raise typer.Exit(1)
        removed, shards = _apply_dedup(db_path, apply_dedup)
        console.print(f"[green]Removed {removed} duplicate entries from {shards} shard files.[/green]")

    if fix_city_variants:
        removed = dedup_city_coverage(db_path)
        if removed:
            console.print(f"[green]Removed {removed} duplicate city name variants from coverage index.[/green]")
        else:
            console.print("[dim]No duplicate city variants found.[/dim]")


@app.command()
def find_library(
    cities: str = typer.Argument(
        ...,
        help="Comma-separated list of cities to look up (e.g. 'Amsterdam, Florence, Rome')"
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
):
    """Find which library folders cover a set of cities.

    Uses the coverage index built during build-library / ingest.
    """
    db_path = library_path / "library_db"
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)

    city_list = [c.strip() for c in cities.split(",") if c.strip()]
    db = LibraryDatabase(db_path)
    matches = db.find_relevant_folders(city_list)

    total_folders = len(db.get_destinations())

    console.print(f"\n[bold]Relevant library folders for:[/bold] {', '.join(city_list)}\n")

    if not matches:
        console.print("[yellow]No matching folders found.[/yellow]")
        console.print("[dim]Try running build-library to refresh the coverage index.[/dim]")
    else:
        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Folder", style="cyan")
        table.add_column("Guides", justify="right")
        table.add_column("Cities covered (sample)", style="dim")

        coverage = db.data.get("_folder_coverage", {})
        for folder, source_files in sorted(matches.items()):
            folder_cities = coverage.get(folder, [])
            # Highlight matched cities
            matched = [c for c in folder_cities if c.lower() in {x.lower() for x in city_list}]
            others = [c for c in folder_cities if c not in matched]
            sample = ", ".join(f"[bold]{c}[/bold]" for c in matched)
            if others:
                extra = ", ".join(others[:3])
                sample += f", {extra}" + ("..." if len(others) > 3 else "")
            table.add_row(folder, str(len(source_files)), sample)

        console.print(table)
        console.print(f"\n[dim]{len(matches)} folder(s) matched out of {total_folders} total.[/dim]")


@app.command()
def verify_library(
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory"
    ),
    sample_size: int = typer.Option(
        10,
        "--sample", "-n",
        help="Number of cities to spot-check in the coverage index"
    ),
):
    """Run quality checks on the library database.

    Verifies coverage completeness, file accounting, restaurant quality,
    and the city-to-folder matching logic.
    """
    from rich.table import Table

    db_path = library_path / "library_db"
    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build-library' first.")
        raise typer.Exit(1)

    db = LibraryDatabase(db_path)
    coverage = db.data.get("_folder_coverage", {})
    processed = db.data.get("_processed_files", {})
    destinations = db.data.get("destinations", {})

    checks: list[tuple[str, bool, str]] = []  # (check name, passed, detail)

    # 1. Coverage completeness: every destination folder has ≥1 city
    folders_missing_coverage = [f for f in destinations if not coverage.get(f)]
    checks.append((
        "Coverage index populated",
        len(folders_missing_coverage) == 0,
        f"{len(folders_missing_coverage)} folder(s) have no cities: {', '.join(folders_missing_coverage[:3])}"
        if folders_missing_coverage else f"{len(coverage)} folder(s) indexed",
    ))

    # 2. File accounting: every file in library subfolders is in _processed_files
    actual_files = {
        str(f.relative_to(library_path))
        for f in library_path.rglob("*")
        if f.suffix.lower() in (".docx", ".pdf")
        and "failed-processing" not in f.parts
    }
    untracked = actual_files - set(processed.keys())
    checks.append((
        "All library files tracked",
        len(untracked) == 0,
        f"{len(untracked)} untracked file(s)" if untracked
        else f"{len(actual_files)} file(s) all accounted for",
    ))

    # 3. Restaurant quality: every restaurant in a sample of destinations has name + cuisine_type
    bad_restaurants = 0
    checked_restaurants = 0
    for dest_data in list(destinations.values())[:10]:
        for r in dest_data.get("restaurants", [])[:20]:
            checked_restaurants += 1
            if not r.get("name") or not r.get("cuisine_type"):
                bad_restaurants += 1
    checks.append((
        "Restaurant data quality",
        bad_restaurants == 0,
        f"{bad_restaurants}/{checked_restaurants} missing name or cuisine_type"
        if bad_restaurants else f"{checked_restaurants} restaurants checked — all have name & cuisine",
    ))

    # 4. No empty destinations
    empty_dests = [
        d for d, data in destinations.items()
        if not data.get("restaurants") and not data.get("attractions")
    ]
    checks.append((
        "No empty destinations",
        len(empty_dests) == 0,
        f"{len(empty_dests)} destination(s) have no restaurants or attractions: {', '.join(empty_dests[:3])}"
        if empty_dests else f"All {len(destinations)} destination(s) have content",
    ))

    # 5. Coverage spot-check: sample cities from the index and verify find_relevant_folders
    import random
    spot_pairs: list[tuple[str, str]] = []
    for folder, cities in coverage.items():
        for city in cities[:2]:
            spot_pairs.append((city, folder))
    if spot_pairs:
        sample = random.sample(spot_pairs, min(sample_size, len(spot_pairs)))
        mismatches = []
        for city, expected_folder in sample:
            result = db.find_relevant_folders([city])
            if expected_folder not in result:
                mismatches.append(f"{city} → expected {expected_folder}, got {list(result.keys())}")
        checks.append((
            f"City→folder spot-check ({len(sample)} samples)",
            len(mismatches) == 0,
            "; ".join(mismatches) if mismatches else f"All {len(sample)} lookups returned correct folder",
        ))

    # Print results
    console.print()
    console.print(Panel.fit("[bold]Library Verification Report[/bold]", border_style="blue"))
    console.print()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail", style="dim")

    all_passed = True
    for name, passed, detail in checks:
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        table.add_row(name, status, detail)
        if not passed:
            all_passed = False

    console.print(table)
    console.print()

    if all_passed:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print("[bold yellow]Some checks failed — review the details above.[/bold yellow]")
        raise typer.Exit(1)


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()

