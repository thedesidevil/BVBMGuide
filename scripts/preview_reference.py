#!/usr/bin/env python3
"""Offline visual check of the structured reference pages: saved run sections re-extracted against a library (no LLM).

Usage: python3 scripts/preview_reference.py [run_dir] [country_json] [out_dir]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.aigv2.guide.build import build_reference_page  # noqa: E402
from src.aigv2.render.document import GuideData  # noqa: E402
from src.aigv2.render2 import frame as F  # noqa: E402
from src.aigv2.render2.render import RENDERERS_BY_NAME  # noqa: E402
from src.aigv2.writing import structured as st  # noqa: E402
from src.aigv2.writing.sections import _LIB, SectionContent  # noqa: E402

KEYS = ("money", "connectivity", "getting_around", "etiquette", "safety")


def build_docx(run_dir: Path, country_json: Path, data: GuideData, out: Path) -> Path:
    cd = json.loads(country_json.read_text(encoding="utf-8"))
    doc = F.new_guide_doc("Dilna K", "Bali")
    _, W = F.add_guide_section(doc, "reference", F.guide_label("Dilna K", "Bali"), first=True)
    for key in KEYS:
        saved = json.loads((run_dir / "sections" / f"{key}.json").read_text(encoding="utf-8"))["content"]
        c = SectionContent.model_validate(saved)
        named = {n: cd.get(n) or [] for _, n in _LIB[key]}
        fields = st.extract(key, named, [])
        if key in ("etiquette",):
            fields = {k: v for k, v in fields.items() if k in ("dos", "donts")} | {"phrases": c.phrases}
        c = c.model_copy(update=fields)
        for comp in build_reference_page(key, c, data).components:
            RENDERERS_BY_NAME[comp.type](doc, W, comp)
        doc.add_page_break()
    doc.save(out)
    return out


if __name__ == "__main__":
    run = Path(sys.argv[1] if len(sys.argv) > 1 else "aigv2_data/runs/20261104-render2-preview")
    cj = Path(sys.argv[2] if len(sys.argv) > 2 else "library_db_new/_country/Indonesia.json")
    outd = Path(sys.argv[3] if len(sys.argv) > 3 else ".superpowers/lookfeel")
    fx = Path("tests/aigv2/fixtures/bali_guide/guide_data.json")
    outd.mkdir(parents=True, exist_ok=True)
    docx = build_docx(run, cj, GuideData.model_validate(json.loads(fx.read_text(encoding="utf-8"))), outd / "a_reference.docx")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from preview_guide import preview
    n = preview(docx, outd / "a_tmp")
    for p in sorted((outd / "a_tmp").glob("page-*.png")):
        p.rename(outd / f"a_{p.name}")
    print(n, "pages")
