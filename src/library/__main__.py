"""CLI for AIG library management: build, ingest, verify, clean."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .builder import LibraryBuilder, LibraryDatabase
from .ingester import LibraryIngester
from .qc import LibraryQC

app = typer.Typer(
    name="library",
    help="Manage the AIG library database",
)
console = Console()


@app.command()
def build(
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory (source files)",
    ),
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Output database path (sharded directory)",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Force re-processing of all files (ignore cache)",
    ),
    workers: int = typer.Option(
        5,
        "--workers", "-w",
        help="Number of parallel AI extraction workers",
        min=1,
        max=20,
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Build the library database using AI extraction."""

    console.print(Panel.fit(
        "[bold blue]Library Database Builder[/bold blue]\n"
        "[dim]Using AI to extract structured data from all guides[/dim]",
        border_style="blue",
    ))

    if force:
        console.print("[yellow]Force mode: Re-processing all files[/yellow]\n")

    try:
        builder = LibraryBuilder(library_path, api_key=api_key, workers=workers)
        console.print(f"[dim]Using AI: {builder.client}[/dim]\n")
        builder.build_database(force=force, output_path=db_path)
    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)


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
        help="Path to the AIG library directory",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from .env if not set)",
    ),
):
    """Classify and move AIG files into the correct library subfolder."""

    console.print(Panel.fit(
        "[bold blue]Library Ingester[/bold blue]\n"
        "[dim]Classifying and moving AIGs into the library[/dim]",
        border_style="blue",
    ))

    try:
        ingester = LibraryIngester(library_path, api_key=api_key)
    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    try:
        count = ingester.ingest(input_path)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if count:
        console.print(f"\n[bold green]{count} file(s) moved.[/bold green]")
        console.print("[dim]Run 'build' to update the database.[/dim]")
    else:
        console.print("\n[dim]Nothing to ingest.[/dim]")


@app.command()
def stats(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
):
    """Show statistics about the library database."""
    from rich.table import Table

    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
        raise typer.Exit(1)

    db = LibraryDatabase(db_path)

    console.print(Panel.fit(
        "[bold]Library Database Statistics[/bold]",
        border_style="blue",
    ))

    processed_files = db.data.get("_processed_files", {})

    console.print(f"\n[dim]Database version:[/dim] {db.data.get('version', 'Unknown')}")
    console.print(f"[dim]Built at:[/dim] {db.data.get('built_at', 'Unknown')}")
    console.print(f"[dim]Files processed:[/dim] {len(processed_files)}")
    console.print(f"\n[bold]Destinations:[/bold] {len(db.get_destinations())}\n")

    table = Table(show_header=True)
    table.add_column("Destination", style="cyan")
    table.add_column("Restaurants", justify="right")
    table.add_column("Attractions", justify="right")
    table.add_column("Local Dishes", justify="right")
    table.add_column("Phrases", justify="right")

    for dest in sorted(db.get_destinations()):
        data = db.data.get("destinations", {}).get(dest)
        if not data:
            continue
        table.add_row(
            dest,
            str(len(data.get("restaurants", []))),
            str(len(data.get("attractions", []))),
            str(len(data.get("local_dishes", []))),
            str(len(data.get("phrases", []))),
        )

    console.print(table)


@app.command()
def verify(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory (for file accounting check)",
    ),
    sample_size: int = typer.Option(
        10,
        "--sample", "-n",
        help="Number of cities to spot-check in the coverage index",
    ),
):
    """Run quality verification checks on the library database."""
    import random
    from rich.table import Table

    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
        raise typer.Exit(1)

    db = LibraryDatabase(db_path)
    coverage = db.data.get("_folder_coverage", {})
    processed = db.data.get("_processed_files", {})
    destinations = db.data.get("destinations", {})

    checks: list[tuple[str, bool, str]] = []

    # 1. Coverage completeness
    folders_missing_coverage = [f for f in destinations if not coverage.get(f)]
    checks.append((
        "Coverage index populated",
        len(folders_missing_coverage) == 0,
        f"{len(folders_missing_coverage)} folder(s) have no cities: {', '.join(folders_missing_coverage[:3])}"
        if folders_missing_coverage else f"{len(coverage)} folder(s) indexed",
    ))

    # 2. File accounting
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

    # 3. Restaurant quality
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

    # 5. Coverage spot-check
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
                mismatches.append(f"{city} -> expected {expected_folder}, got {list(result.keys())}")
        checks.append((
            f"City->folder spot-check ({len(sample)} samples)",
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
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
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


@app.command()
def find(
    cities: str = typer.Argument(
        ...,
        help="Comma-separated list of cities (e.g. 'Amsterdam, Florence, Rome')",
    ),
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
):
    """Find which library folders cover a set of cities."""
    from rich.table import Table

    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
        raise typer.Exit(1)

    city_list = [c.strip() for c in cities.split(",") if c.strip()]
    db = LibraryDatabase(db_path)
    matches = db.find_relevant_folders(city_list)

    total_folders = len(db.get_destinations())

    console.print(f"\n[bold]Relevant library folders for:[/bold] {', '.join(city_list)}\n")

    if not matches:
        console.print("[yellow]No matching folders found.[/yellow]")
    else:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Folder", style="cyan")
        table.add_column("Guides", justify="right")
        table.add_column("Cities covered (sample)", style="dim")

        coverage = db.data.get("_folder_coverage", {})
        for folder, source_files in sorted(matches.items()):
            folder_cities = coverage.get(folder, [])
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
def qc(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory (for source verification)",
    ),
    verify_sources: bool = typer.Option(
        False,
        "--verify-sources", "-v",
        help="Enable source document verification",
    ),
    sample_size: int = typer.Option(
        3,
        "--sample", "-n",
        help="Restaurants to verify per destination (with --verify-sources)",
    ),
    max_dests: int = typer.Option(
        20,
        "--max-dests",
        help="Maximum destinations to sample for source verification",
    ),
    spot_check: bool = typer.Option(
        False,
        "--spot-check",
        help="Print sampled unique values per attribute for manual review",
    ),
    spot_count: int = typer.Option(
        50,
        "--spot-count",
        help="Number of unique values to sample per attribute in spot-check mode",
    ),
    severity: str = typer.Option(
        "warning",
        "--severity", "-s",
        help="Minimum severity to display: critical, warning, or info",
    ),
    output_json: Optional[Path] = typer.Option(
        None,
        "--json",
        help="Save full report as JSON file",
    ),
):
    """Run comprehensive quality checks on the library database."""
    from .qc import print_report, print_spot_check

    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
        raise typer.Exit(1)

    qc_runner = LibraryQC(db_path, library_path)

    if spot_check:
        console.print(Panel.fit(
            "[bold]Library Spot Check[/bold]\n"
            f"[dim]Sampling {spot_count} unique values per attribute[/dim]",
            border_style="blue",
        ))
        samples = qc_runner.spot_check(sample_count=spot_count)
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
        report = qc_runner.run(
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
def clean(
    db_path: Path = typer.Option(
        Path("library_db"),
        "--db",
        help="Path to the library database directory",
    ),
    dump: Optional[Path] = typer.Option(
        None,
        "--dump",
        help="Dump contaminated entries to a TSV file for review",
    ),
    apply: Optional[Path] = typer.Option(
        None,
        "--apply",
        help="Apply a reviewed TSV file to remove contaminated entries",
    ),
    dump_dupes: Optional[Path] = typer.Option(
        None,
        "--dump-dupes",
        help="Dump near-duplicate restaurant pairs to a TSV for review",
    ),
    apply_dedup: Optional[Path] = typer.Option(
        None,
        "--apply-dedup",
        help="Apply a reviewed duplicates TSV to merge/remove entries",
    ),
    fix_city_variants: bool = typer.Option(
        False,
        "--fix-city-variants",
        help="Deduplicate city name variants in the coverage index",
    ),
):
    """Clean contaminated or duplicate entries from the library database."""
    from .qc import dump_contamination, apply_cleanup, dump_duplicates, apply_dedup as _apply_dedup, dedup_city_coverage

    if not db_path.exists():
        console.print("[red]Database not found.[/red] Run 'build' first.")
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

    if apply_dedup:
        if not apply_dedup.exists():
            console.print(f"[red]File not found: {apply_dedup}[/red]")
            raise typer.Exit(1)
        removed, shards = _apply_dedup(db_path, apply_dedup)
        console.print(f"[green]Removed {removed} duplicate entries from {shards} shard files.[/green]")

    if fix_city_variants:
        removed = dedup_city_coverage(db_path)
        if removed:
            console.print(f"[green]Removed {removed} duplicate city name variants.[/green]")
        else:
            console.print("[dim]No duplicate city variants found.[/dim]")


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
        help="Show only this field (restaurants, attractions, hotels, etc.)",
    ),
    library_path: Path = typer.Option(
        Path("aig-library"),
        "--library", "-l",
        help="Path to the AIG library directory",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="API key (uses AI_API_KEY from env if not set)",
    ),
):
    """Re-extract and display data from a single AIG file for spot-checking."""
    import json as _json

    try:
        builder = LibraryBuilder(library_path, api_key=api_key)
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

    src = str(file_path)
    for section in ("restaurants", "attractions", "hotels", "local_dishes"):
        for item in data.get(section) or []:
            if isinstance(item, dict):
                item["source_files"] = [src]

    output = {field: data[field] for field in [field] if field and field in data} if field else data
    print(_json.dumps(output, indent=2, ensure_ascii=False))


def main():
    app()


if __name__ == "__main__":
    main()
