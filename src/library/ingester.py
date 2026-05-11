"""Classify and move new AIG files from an input folder into the library."""

import json
import shutil
from pathlib import Path
from typing import Optional

import fitz
from docx import Document
from rich.console import Console

from src.common.ai_provider import get_ai_client

console = Console()

_CLASSIFY_PROMPT = """\
You are classifying a travel guide document to decide which destination folder it belongs in.

Available folders:
{folders}

Document title / filename: {filename}

First 3000 characters of the document:
{preview}

Task: Decide which folder this document belongs in. If one of the existing folders is a good fit, use it exactly as written. If no existing folder fits, suggest a concise new folder name (e.g. "Morocco", "New Zealand").

Return ONLY a JSON object: {{"folder": "<folder name>"}}"""


class LibraryIngester:
    """Classifies and moves new AIG files from an input folder into the library."""

    def __init__(
        self,
        library_path: str | Path,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.library_path = Path(library_path)
        self.client = get_ai_client(api_key=api_key, base_url=base_url, model=model)

    def ingest(self, input_path: Path) -> int:
        """Classify and move all AIG files from input_path into the library. Returns count moved."""
        staged_files = [
            f for f in input_path.iterdir()
            if f.suffix.lower() in (".docx", ".pdf") and f.is_file()
        ]

        if not staged_files:
            console.print("[dim]No files found — nothing to ingest.[/dim]")
            return 0

        console.print(f"\n[bold]Found {len(staged_files)} file(s) to classify[/bold]\n")

        existing_folders = sorted(f.name for f in self.library_path.iterdir() if f.is_dir())
        ingested = 0

        for file_path in staged_files:
            console.print(f"[cyan]→[/cyan] {file_path.name}")

            folder = self._classify_file(file_path, existing_folders)
            if not folder:
                console.print(f"  [yellow]Could not classify {file_path.name} — skipping.[/yellow]")
                continue

            dest_dir = self.library_path / folder
            dest_dir.mkdir(exist_ok=True)
            dest_file = dest_dir / file_path.name

            if dest_file.exists():
                console.print(f"  [dim]{file_path.name} already exists in {folder}/ — skipping.[/dim]")
            else:
                shutil.move(str(file_path), dest_file)
                console.print(f"  [green]✓[/green] {file_path.name} → {folder}/")
                ingested += 1

            if folder not in existing_folders:
                existing_folders.append(folder)

        return ingested

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_file(self, file_path: Path, existing_folders: list[str]) -> Optional[str]:
        """Ask AI which library folder this file belongs in."""
        try:
            preview = self._extract_preview(file_path, max_chars=3000)
        except Exception:
            preview = "(could not read file)"

        folders_list = "\n".join(f"  - {f}" for f in existing_folders) if existing_folders else "  (none yet)"
        prompt = _CLASSIFY_PROMPT.format(
            folders=folders_list,
            filename=file_path.name,
            preview=preview,
        )

        try:
            resp = self.client.complete(prompt, max_tokens=64, temperature=0)
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("```")[1]
                if resp.startswith("json"):
                    resp = resp[4:]
                resp = resp.strip("` \n")
            data = json.loads(resp)
            folder = data.get("folder", "").strip()
            return folder if folder else None
        except Exception as e:
            console.print(f"  [dim]Classification error: {e}[/dim]")
            return None

    def _extract_preview(self, file_path: Path, max_chars: int = 3000) -> str:
        if file_path.suffix.lower() == ".pdf":
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        else:
            doc_obj = Document(file_path)
            text = "\n".join(p.text for p in doc_obj.paragraphs if p.text.strip())
        return text[:max_chars]
