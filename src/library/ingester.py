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

Rules:
- Folders are named for a country or a group of neighbouring countries.
- NEVER pick a continent or region folder such as "Europe" or "Asia" for a guide that names specific countries.
- For a guide covering several countries, choose the folder of the FIRST country named in the title or itinerary (the other countries are recorded separately).
- If there is no folder for that country, suggest a concise new country name.

Reply with ONLY the JSON object, no explanation: {{"folder": "<folder name>"}}"""


def _parse_folder_reply(resp: str) -> dict:
    """Whole reply as JSON, else the LAST JSON object containing a "folder" key."""
    text = (resp or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    found = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, dict) and "folder" in obj:
            found = obj
    if found is None:
        raise ValueError(f"no folder JSON in reply: {text[:80]}")
    return found


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
        """Ask AI which library folder this file belongs in (None on any failure)."""
        folder, error = self._classify_file_checked(file_path, existing_folders)
        if error:
            console.print(f"  [dim]Classification error: {error}[/dim]")
        return folder

    def _classify_file_checked(self, file_path: Path, existing_folders: list[str]) -> tuple[Optional[str], Optional[str]]:
        """Like ``_classify_file`` but returns ``(folder, error)``: ``error`` is set only
        when the call or its parsing FAILED, not when the model answered with no folder."""
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
            resp = self.client.complete(prompt, max_tokens=512, temperature=0)
            data = _parse_folder_reply(resp)
            folder = str(data.get("folder") or "").strip()
            return (folder if folder else None), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def _extract_preview(self, file_path: Path, max_chars: int = 3000) -> str:
        if file_path.suffix.lower() == ".pdf":
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        else:
            doc_obj = Document(file_path)
            text = "\n".join(p.text for p in doc_obj.paragraphs if p.text.strip())
        return text[:max_chars]
