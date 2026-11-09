#!/usr/bin/env python3
"""Render a run's guide.docx to PDF + PNG pages for a quick visual check.

Usage: python3 scripts/preview_guide.py <run_id|path.docx> [--data-root aigv2_data] [--dpi 70]
Output goes to <run folder>/preview/ (guide.pdf, page-01.png ...).
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class PreviewError(Exception):
    pass


def find_docx(target: str, data_root: str = "aigv2_data") -> Path:
    p = Path(target)
    if p.suffix.lower() == ".docx":
        if not p.is_file():
            raise PreviewError(f"docx not found: {p}")
        return p
    docx = Path(data_root) / "runs" / target / "guide.docx"
    if not docx.is_file():
        raise PreviewError(f"guide.docx not found for run {target!r} (looked at {docx})")
    return docx


def _copy_fonts(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    pats = ["/System/Library/Fonts/Supplemental/Georgia*.ttf",
            os.path.expanduser("~/Library/Fonts/CormorantGaramond-*.ttf"),
            os.path.expanduser("~/.fonts/CormorantGaramond-*.ttf")]
    for pat in pats:
        for f in glob.glob(pat):
            shutil.copy(f, dest)


def preview(docx_path, out_dir, dpi: int = 70) -> int:
    """Convert docx to out_dir/guide.pdf and out_dir/page-NN.png; return page count."""
    docx_path, out_dir = Path(docx_path), Path(out_dir)
    if not docx_path.is_file():
        raise PreviewError(f"docx not found: {docx_path}")
    for tool in ("soffice", "pdftoppm"):
        if not shutil.which(tool):
            raise PreviewError(f"{tool} not found on PATH; install LibreOffice/poppler")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page-*.png"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profile"
        _copy_fonts(profile / "user" / "fonts")
        conv = Path(tmp) / "out"
        r = subprocess.run(
            ["soffice", f"-env:UserInstallation={profile.resolve().as_uri()}", "--headless",
             "--convert-to", "pdf", "--outdir", str(conv), str(docx_path.resolve())],
            capture_output=True, text=True, timeout=300)
        pdf = conv / (docx_path.stem + ".pdf")
        if not pdf.is_file():
            raise PreviewError(f"LibreOffice conversion failed: {(r.stderr or r.stdout).strip()}")
        shutil.copy(pdf, out_dir / "guide.pdf")
    r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(out_dir / "guide.pdf"),
                        str(out_dir / "page")], capture_output=True, text=True)
    if r.returncode != 0:
        raise PreviewError(f"pdftoppm failed: {r.stderr.strip()}")
    pages = sorted(out_dir.glob("page-*.png"))
    # normalise names to page-01.png style regardless of pdftoppm's padding
    width = max(2, len(str(len(pages))))
    for i, f in enumerate(pages, 1):
        new = out_dir / f"page-{i:0{width}d}.png"
        if f != new:
            f.rename(new)
    return len(pages)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="run id or path to a .docx")
    ap.add_argument("--data-root", default="aigv2_data")
    ap.add_argument("--dpi", type=int, default=70)
    a = ap.parse_args(argv)
    try:
        docx = find_docx(a.target, a.data_root)
        out = docx.parent / "preview"
        n = preview(docx, out, a.dpi)
    except PreviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{out}\n{n} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
