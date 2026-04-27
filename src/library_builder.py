"""Build a structured database from the AIG library using AI extraction."""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF for PDF extraction
from docx import Document
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .models import Restaurant
from .ai_provider import get_ai_client


console = Console()

# Database schema version
DB_VERSION = "1.1"


class LibraryBuilder:
    """Builds a structured database from the AIG library using AI."""
    
    def __init__(
        self,
        library_path: str | Path,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.library_path = Path(library_path)
        self.client = get_ai_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model
        )
    
    def build_database(self, output_path: Optional[Path] = None, force: bool = False) -> dict:
        """Build the complete library database.
        
        Args:
            output_path: Where to save the database (default: library_db.json)
            force: If True, reprocess all files. If False, only process new/modified files.
        """
        if output_path is None:
            output_path = self.library_path / "library_db.json"
        
        # Load existing database if it exists (for incremental builds)
        existing_db = None
        processed_files = {}  # filename -> {mtime, destination}
        
        if output_path.exists() and not force:
            try:
                with open(output_path, 'r', encoding='utf-8') as f:
                    existing_db = json.load(f)
                processed_files = existing_db.get("_processed_files", {})
                console.print(f"[dim]Found existing database with {len(processed_files)} processed files[/dim]")
            except Exception:
                existing_db = None
        
        database = {
            "version": DB_VERSION,
            "built_at": datetime.now().isoformat(),
            "destinations": existing_db.get("destinations", {}) if existing_db else {},
            "_processed_files": processed_files
        }
        
        # Find all DOCX and PDF files
        docx_files = list(self.library_path.glob("*.docx"))
        pdf_files = list(self.library_path.glob("*.pdf"))
        all_files = docx_files + pdf_files
        
        # Determine which files need processing
        files_to_process = []
        for file_path in all_files:
            filename = file_path.name
            file_mtime = os.path.getmtime(file_path)
            
            # Check if file was already processed and hasn't changed
            if filename in processed_files:
                if processed_files[filename].get("mtime") == file_mtime:
                    continue  # Skip - already processed and unchanged
            
            files_to_process.append(file_path)
        
        if not files_to_process:
            console.print("\n[green]✓ All files already processed. Database is up to date.[/green]")
            return database
        
        console.print(f"\n[bold]Building library database...[/bold]")
        console.print(f"  Total files: {len(all_files)} ({len(docx_files)} DOCX, {len(pdf_files)} PDF)")
        console.print(f"  Already processed: {len(all_files) - len(files_to_process)}")
        console.print(f"  To process: {len(files_to_process)}\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Processing files...", total=len(files_to_process))
            
            for file_path in files_to_process:
                progress.update(task, description=f"Processing {file_path.name[:40]}...")
                
                try:
                    file_data = self._process_file(file_path)
                    if file_data:
                        destination = file_data.get("destination", "Unknown")
                        
                        if destination not in database["destinations"]:
                            database["destinations"][destination] = {
                                "restaurants": [],
                                "attractions": [],
                                "hotels": [],
                                "local_dishes": [],
                                "phrases": [],
                                "safety_tips": [],
                                "source_files": []
                            }
                        
                        dest_data = database["destinations"][destination]
                        
                        # Add source file if not already present
                        if file_path.name not in dest_data["source_files"]:
                            dest_data["source_files"].append(file_path.name)
                        
                        # Merge data
                        if file_data.get("restaurants"):
                            dest_data["restaurants"].extend(file_data["restaurants"])
                        if file_data.get("attractions"):
                            dest_data["attractions"].extend(file_data["attractions"])
                        if file_data.get("hotels"):
                            dest_data["hotels"].extend(file_data["hotels"])
                        if file_data.get("local_dishes"):
                            dest_data["local_dishes"].extend(file_data["local_dishes"])
                        if file_data.get("phrases"):
                            dest_data["phrases"].extend(file_data["phrases"])
                        if file_data.get("safety_tips"):
                            dest_data["safety_tips"].extend(file_data["safety_tips"])
                        
                        # Track this file as processed
                        database["_processed_files"][file_path.name] = {
                            "mtime": os.path.getmtime(file_path),
                            "destination": destination,
                            "processed_at": datetime.now().isoformat()
                        }
                
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to process {file_path.name}: {e}[/yellow]")
                
                progress.advance(task)
        
        # Deduplicate entries
        for dest, data in database["destinations"].items():
            data["restaurants"] = self._deduplicate_restaurants(data["restaurants"])
            data["attractions"] = self._deduplicate_by_name(data["attractions"])
            data["local_dishes"] = self._deduplicate_by_name(data["local_dishes"])
        
        # Save database
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        
        console.print(f"\n[bold green]✓ Database saved to {output_path}[/bold green]")
        
        # Print summary
        self._print_summary(database)
        
        return database
    
    def _process_file(self, file_path: Path) -> Optional[dict]:
        """Process a single DOCX or PDF file using AI extraction."""
        # Extract text based on file type
        try:
            if file_path.suffix.lower() == '.pdf':
                full_text = self._extract_text_from_pdf(file_path)
            else:
                full_text = self._extract_text_from_docx(file_path)
        except Exception as e:
            console.print(f"[dim]Failed to extract text from {file_path.name}: {e}[/dim]")
            return None
        
        # Skip very short files
        if len(full_text) < 200:
            return None
        
        # Truncate if too long (API limits)
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n...[truncated]"
        
        # Use AI to extract structured data
        prompt = f"""Extract structured travel information from this All Inclusive Guide document.

DOCUMENT:
{full_text}

Return a JSON object with:
{{
  "destination": "Country or city name",
  "restaurants": [
    {{
      "name": "Restaurant Name",
      "cuisine_type": ["Local", "Italian", etc],
      "price_range": "₹₹ or budget/mid-range/luxury",
      "hours": "Opening hours",
      "ambience": "Brief description",
      "must_try_dishes": ["Dish 1", "Dish 2"],
      "distance_from_hotel": "X min walk/drive",
      "best_for": ["romantic", "family", "casual"],
      "vegetarian_friendly": true/false,
      "google_maps_link": "URL if present"
    }}
  ],
  "attractions": [
    {{
      "name": "Attraction Name",
      "description": "Brief description",
      "hours": "Opening hours",
      "entry_fee": "Cost",
      "recommended_duration": "X hours",
      "google_maps_link": "URL if present"
    }}
  ],
  "hotels": [
    {{
      "name": "Hotel Name",
      "location": "Area/neighborhood",
      "google_maps_link": "URL if present"
    }}
  ],
  "local_dishes": [
    {{
      "name": "Dish Name",
      "description": "What it is",
      "vegetarian": true/false,
      "where_to_try": "Restaurant or place name"
    }}
  ],
  "phrases": [
    {{
      "english": "Hello",
      "local": "Bonjour",
      "category": "greeting/polite/food/emergency"
    }}
  ],
  "safety_tips": ["Tip 1", "Tip 2"]
}}

IMPORTANT:
- Extract ALL restaurants mentioned, not just a few
- Include all details provided (hours, prices, dishes)
- For restaurants, capture the ambience/description
- If a field is not mentioned, omit it or use null
- Return ONLY valid JSON, no explanation"""

        try:
            result_text = self.client.complete(prompt, max_tokens=8000)
            
            # Clean up potential markdown
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            
            return json.loads(result_text.strip())
        
        except Exception as e:
            console.print(f"[dim]AI extraction failed for {file_path.name}: {e}[/dim]")
            return None
    
    def _extract_text_from_docx(self, docx_path: Path) -> str:
        """Extract text from a DOCX file."""
        doc = Document(docx_path)
        return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    
    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from a PDF file."""
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    
    def _deduplicate_restaurants(self, restaurants: list) -> list:
        """Deduplicate restaurants by name, keeping the most complete entry."""
        seen = {}
        
        for r in restaurants:
            name = r.get("name", "").lower().strip()
            if not name:
                continue
            
            if name not in seen:
                seen[name] = r
            else:
                # Merge: keep more complete version
                existing = seen[name]
                for key, value in r.items():
                    if value and not existing.get(key):
                        existing[key] = value
        
        return list(seen.values())
    
    def _deduplicate_by_name(self, items: list) -> list:
        """Deduplicate items by name field."""
        seen = set()
        result = []
        
        for item in items:
            name = item.get("name", "").lower().strip()
            if name and name not in seen:
                seen.add(name)
                result.append(item)
        
        return result
    
    def _print_summary(self, database: dict) -> None:
        """Print a summary of the built database."""
        console.print("\n[bold]📊 Library Database Summary[/bold]\n")
        
        for dest, data in sorted(database["destinations"].items()):
            console.print(f"  [cyan]{dest}[/cyan]")
            console.print(f"    Restaurants: {len(data['restaurants'])}")
            console.print(f"    Attractions: {len(data['attractions'])}")
            console.print(f"    Local Dishes: {len(data['local_dishes'])}")
            console.print(f"    Source Files: {len(data['source_files'])}")
            console.print()


class LibraryDatabase:
    """Query interface for the pre-built library database."""
    
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._data = None
    
    def load(self) -> None:
        """Load the database from disk."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Library database not found: {self.db_path}")
        
        with open(self.db_path, 'r', encoding='utf-8') as f:
            self._data = json.load(f)
    
    @property
    def data(self) -> dict:
        if self._data is None:
            self.load()
        return self._data
    
    def get_destinations(self) -> list[str]:
        """Get all destinations in the database."""
        return list(self.data["destinations"].keys())
    
    def get_restaurants(self, destination: str) -> list[dict]:
        """Get all restaurants for a destination."""
        dest_lower = destination.lower()
        
        for dest, data in self.data["destinations"].items():
            if dest.lower() == dest_lower:
                return data.get("restaurants", [])
        
        return []
    
    def get_attractions(self, destination: str) -> list[dict]:
        """Get all attractions for a destination."""
        dest_lower = destination.lower()
        
        for dest, data in self.data["destinations"].items():
            if dest.lower() == dest_lower:
                return data.get("attractions", [])
        
        return []
    
    def get_local_dishes(self, destination: str) -> list[dict]:
        """Get local dishes for a destination."""
        dest_lower = destination.lower()
        
        for dest, data in self.data["destinations"].items():
            if dest.lower() == dest_lower:
                return data.get("local_dishes", [])
        
        return []
    
    def get_phrases(self, destination: str) -> list[dict]:
        """Get useful phrases for a destination."""
        dest_lower = destination.lower()
        
        for dest, data in self.data["destinations"].items():
            if dest.lower() == dest_lower:
                return data.get("phrases", [])
        
        return []
    
    def search_restaurants(
        self, 
        destination: str,
        vegetarian_only: bool = False,
        cuisine_types: Optional[list[str]] = None,
        budget: Optional[str] = None
    ) -> list[dict]:
        """Search restaurants with filters."""
        restaurants = self.get_restaurants(destination)
        results = []
        
        for r in restaurants:
            # Vegetarian filter
            if vegetarian_only and not r.get("vegetarian_friendly"):
                continue
            
            # Cuisine filter
            if cuisine_types:
                r_cuisines = [c.lower() for c in r.get("cuisine_type", [])]
                if not any(c.lower() in r_cuisines for c in cuisine_types):
                    continue
            
            # Budget filter (simplified)
            if budget:
                r_price = r.get("price_range", "").lower()
                if budget == "budget" and "₹₹₹" in r_price:
                    continue
                elif budget == "luxury" and "₹" not in r_price:
                    continue
            
            results.append(r)
        
        return results


def build_library(library_path: str, api_key: Optional[str] = None) -> Path:
    """Convenience function to build the library database."""
    builder = LibraryBuilder(library_path, api_key)
    output_path = Path(library_path) / "library_db.json"
    builder.build_database(output_path)
    return output_path

