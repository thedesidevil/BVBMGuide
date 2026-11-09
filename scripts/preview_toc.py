#!/usr/bin/env python3
"""Render ONLY the contents page of a saved guide, for a quick visual check.

Usage: python3 scripts/preview_toc.py <guide.json|run_id> [--out DIR] [--data-root aigv2_data] [--dpi 110]
Writes toc_only.docx + PNG/PDF preview into DIR (default .superpowers/lookfeel/toc_only/).
Page numbers: measured from the run's existing guide*.docx when soffice is available, else sequential fakes.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.aigv2.guide.model import Guide  # noqa: E402
from src.aigv2.render2 import document as D  # noqa: E402
from src.aigv2.render2 import frame as F  # noqa: E402
from src.aigv2.render2 import toc as TOC  # noqa: E402


def find_guide(target: str, data_root: str) -> Path:
    p = Path(target)
    if p.suffix == ".json" and p.is_file():
        return p
    q = Path(data_root) / "runs" / target / "guide.json"
    if not q.is_file():
        raise SystemExit(f"guide.json not found: {target}")
    return q


def pages_for(guide: Guide, gpath: Path) -> dict:
    titles = {p.bookmark: D._heading(p) for p in guide.pages if p.kind in ("day", "reference", "thank_you")}
    full = next(iter(sorted(gpath.parent.glob("guide*.docx"))), None)
    if full is not None:
        skip = D._skip_pages(full.read_bytes(), guide, titles, 1)
        got = TOC.page_map(full.read_bytes(), titles, skip_pages=skip)
        if got:
            return got
    return {b: i + 3 for i, b in enumerate(titles)}


def build(guide: Guide, pages: dict, out: Path, font_scale: float = 1.0) -> Path:
    doc = F.new_guide_doc(guide.client, guide.destination)
    F.add_guide_section(doc, "toc", F.guide_label(guide.client, guide.destination), first=True)
    TOC.render_toc(doc, guide, pages)
    if font_scale != 1.0:  # worst-case simulation: entry-table type wider (cells keep their 1.0x widths)
        from docx.oxml.ns import qn
        for tr in doc.element.body.iter(qn("w:tr")):
            if len(tr.findall(qn("w:tc"))) == 3:
                for sz in tr.iter(qn("w:sz")):
                    sz.set(qn("w:val"), str(round(int(sz.get(qn("w:val"))) * font_scale)))
    out.mkdir(parents=True, exist_ok=True)
    path = out / "toc_only.docx"
    doc.save(str(path))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--out", default=str(ROOT / ".superpowers/lookfeel/toc_only"))
    ap.add_argument("--data-root", default=str(ROOT / "aigv2_data"))
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--font-scale", type=float, default=1.0, help="simulate wider entry fonts (e.g. 1.2)")
    a = ap.parse_args()
    gpath = find_guide(a.target, a.data_root)
    guide = Guide.model_validate_json(gpath.read_text())
    out = Path(a.out)
    docx = build(guide, pages_for(guide, gpath), out, a.font_scale)
    from preview_guide import preview
    n = preview(docx, out, dpi=a.dpi)
    print(docx)
    print(out / "page-1.png" if (out / "page-1.png").exists() else out / "page-01.png", f"({n} page(s))")


if __name__ == "__main__":
    main()
