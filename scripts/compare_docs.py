"""
compare_docs.py — Side-by-side formatting diff for two .docx files.

Usage:
    python scripts/compare_docs.py [input.docx] [output.docx] [--page N]

Defaults:
    input  = "input/Hotel Options - new design - hand-curated.docx"
    output = "input/Hotel Options - new design - code created.docx"
    page   = all pages

Output:
    Per-element table showing INPUT vs OUTPUT values; only rows that differ
    are flagged with  !!  so you can scan quickly.
"""
from __future__ import annotations
import sys
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table


# ── helpers ──────────────────────────────────────────────────────────────────

def _rgb(font):
    try:
        if font.color and font.color.type and font.color.rgb:
            return f"#{font.color.rgb}"
    except Exception:
        pass
    return None

def _pt(val):
    try:
        return f"{val.pt:.1f}pt" if val is not None else None
    except Exception:
        return str(val) if val is not None else None

def _cell_margins(cell):
    tcPr = cell._tc.find(qn('w:tcPr'))
    if tcPr is None:
        return "inherit"
    tcMar = tcPr.find(qn('w:tcMar'))
    if tcMar is None:
        return "inherit"
    out = {}
    for side in ['top', 'bottom', 'left', 'right']:
        el = tcMar.find(qn(f'w:{side}'))
        if el is not None:
            w = el.get(qn('w:w'))
            if w:
                out[side] = f"{int(w)/20:.1f}pt"
    return out or "inherit"

def _row_height(row):
    trPr = row._tr.find(qn('w:trPr'))
    if trPr is None:
        return "auto"
    trH = trPr.find(qn('w:trHeight'))
    if trH is None:
        return "auto"
    val = trH.get(qn('w:val'))
    rule = trH.get(qn('w:hRule'), 'auto')
    return f"{int(val)/20:.1f}pt ({rule})" if val else "auto"


# ── extraction ────────────────────────────────────────────────────────────────

def extract_pages(path: str) -> dict[int, list[dict]]:
    """Return {page_number: [element_dict, ...]}."""
    doc = Document(path)
    body = doc.element.body
    pages: dict[int, list[dict]] = {}
    page = 1

    for child in body:
        tag = child.tag.split('}')[-1]

        if tag == 'p':
            para = Paragraph(child, doc)
            for br in child.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br'):
                if br.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type') == 'page':
                    page += 1
            pf = para.paragraph_format
            has_image = bool(child.findall('.//' + qn('a:blip')))
            runs = []
            for run in para.runs:
                if not run.text:
                    continue
                font = run.font
                runs.append({
                    'text': run.text,
                    'font': font.name,
                    'size': _pt(font.size),
                    'bold': font.bold,
                    'italic': font.italic,
                    'color': _rgb(font),
                })
            pages.setdefault(page, []).append({
                'type': 'para',
                'text': para.text.strip(),
                'style': para.style.name,
                'align': str(para.alignment).replace('WD_ALIGN_PARAGRAPH.', '') if para.alignment else None,
                'sb': _pt(pf.space_before),
                'sa': _pt(pf.space_after),
                'image': has_image,
                'runs': runs,
            })

        elif tag == 'tbl':
            tbl = Table(child, doc)
            rows_data = []
            for r, row in enumerate(tbl.rows):
                cells_data = []
                for c, cell in enumerate(row.cells):
                    cell_runs = []
                    for para in cell.paragraphs:
                        pf = para.paragraph_format
                        for run in para.runs:
                            if not run.text:
                                continue
                            font = run.font
                            cell_runs.append({
                                'text': run.text,
                                'font': font.name,
                                'size': _pt(font.size),
                                'bold': font.bold,
                                'italic': font.italic,
                                'color': _rgb(font),
                                'sb': _pt(pf.space_before),
                                'sa': _pt(pf.space_after),
                                'align': str(para.alignment).replace('WD_ALIGN_PARAGRAPH.', '') if para.alignment else None,
                            })
                    cells_data.append({
                        'text': cell.text.strip(),
                        'margins': _cell_margins(cell),
                        'runs': cell_runs,
                    })
                rows_data.append({
                    'height': _row_height(row),
                    'cells': cells_data,
                })
            pages.setdefault(page, []).append({
                'type': 'table',
                'rows': rows_data,
            })

    return pages


# ── diff printing ─────────────────────────────────────────────────────────────

W = 42  # column width for values

def _flag(a, b):
    return "  !!" if str(a) != str(b) else "    "

def _row(label, a, b):
    flag = _flag(a, b)
    print(f"  {label:<28} {str(a):<{W}} {str(b):<{W}}{flag}")

def _hdr(title):
    print(f"\n  {'─'*28}  {title}")

def compare_pages(input_path: str, output_path: str, only_page: int | None = None):
    inp = extract_pages(input_path)
    out = extract_pages(output_path)

    all_pages = sorted(set(inp) | set(out))
    if only_page is not None:
        all_pages = [only_page]

    for pg in all_pages:
        print(f"\n{'━'*100}")
        print(f"  PAGE {pg}")
        print(f"{'━'*100}")
        print(f"  {'':28}  {'INPUT':<{W}} {'OUTPUT':<{W}}")
        print(f"  {'─'*28}  {'─'*W} {'─'*W}")

        in_elems  = inp.get(pg, [])
        out_elems = out.get(pg, [])
        max_elems = max(len(in_elems), len(out_elems))

        for i in range(max_elems):
            ie = in_elems[i]  if i < len(in_elems)  else None
            oe = out_elems[i] if i < len(out_elems) else None

            if ie is None:
                print(f"\n  [elem {i}] INPUT: (missing)  OUTPUT: {oe['type'] if oe else '?'}")
                continue
            if oe is None:
                print(f"\n  [elem {i}] INPUT: {ie['type']}  OUTPUT: (missing)")
                continue

            if ie['type'] == 'para' and oe['type'] == 'para':
                label = (ie.get('text') or '(blank)')[:35]
                _hdr(f"[para {i}] {label!r}")
                _row("style",  ie['style'],  oe['style'])
                _row("align",  ie['align'],  oe['align'])
                _row("space_before", ie['sb'], oe['sb'])
                _row("space_after",  ie['sa'], oe['sa'])
                _row("image",  ie['image'],  oe['image'])
                if ie['text'] != oe['text']:
                    print(f"  {'text':<28} {ie['text'][:W]:<{W}} {oe['text'][:W]:<{W}}  !!")

                # Compare runs side by side
                in_runs  = ie['runs']
                out_runs = oe['runs']
                max_runs = max(len(in_runs), len(out_runs), 1)
                for ri in range(max_runs):
                    ir = in_runs[ri]  if ri < len(in_runs)  else {}
                    or_ = out_runs[ri] if ri < len(out_runs) else {}
                    prefix = f"run[{ri}]"
                    _row(f"  {prefix}.font",   ir.get('font'),   or_.get('font'))
                    _row(f"  {prefix}.size",   ir.get('size'),   or_.get('size'))
                    _row(f"  {prefix}.bold",   ir.get('bold'),   or_.get('bold'))
                    _row(f"  {prefix}.italic", ir.get('italic'), or_.get('italic'))
                    _row(f"  {prefix}.color",  ir.get('color'),  or_.get('color'))

            elif ie['type'] == 'table' and oe['type'] == 'table':
                _hdr(f"[table {i}]  {len(ie['rows'])}r×{len(ie.get('rows',[{}])[0].get('cells',[]))}c"
                     f" vs {len(oe['rows'])}r×{len(oe.get('rows',[{}])[0].get('cells',[]))}c")
                in_rows  = ie['rows']
                out_rows = oe['rows']
                for ri in range(max(len(in_rows), len(out_rows))):
                    ir = in_rows[ri]  if ri < len(in_rows)  else None
                    or_ = out_rows[ri] if ri < len(out_rows) else None
                    _row(f"  row[{ri}].height",
                         ir['height'] if ir else '(missing)',
                         or_['height'] if or_ else '(missing)')
                    in_cells  = ir['cells']  if ir  else []
                    out_cells = or_['cells'] if or_ else []
                    for ci in range(max(len(in_cells), len(out_cells))):
                        ic = in_cells[ci]  if ci < len(in_cells)  else {}
                        oc = out_cells[ci] if ci < len(out_cells) else {}
                        _row(f"  [{ri},{ci}].text",    (ic.get('text') or '')[:W], (oc.get('text') or '')[:W])
                        _row(f"  [{ri},{ci}].margins", ic.get('margins', '?'),     oc.get('margins', '?'))
                        in_runs  = ic.get('runs', [])
                        out_runs = oc.get('runs', [])
                        for rri in range(max(len(in_runs), len(out_runs), 1)):
                            irr = in_runs[rri]  if rri < len(in_runs)  else {}
                            orr = out_runs[rri] if rri < len(out_runs) else {}
                            _row(f"  [{ri},{ci}]run[{rri}].font",   irr.get('font'),   orr.get('font'))
                            _row(f"  [{ri},{ci}]run[{rri}].size",   irr.get('size'),   orr.get('size'))
                            _row(f"  [{ri},{ci}]run[{rri}].bold",   irr.get('bold'),   orr.get('bold'))
                            _row(f"  [{ri},{ci}]run[{rri}].color",  irr.get('color'),  orr.get('color'))
                            _row(f"  [{ri},{ci}]run[{rri}].sb",     irr.get('sb'),     orr.get('sb'))
                            _row(f"  [{ri},{ci}]run[{rri}].sa",     irr.get('sa'),     orr.get('sa'))
            else:
                print(f"\n  [elem {i}] type mismatch: INPUT={ie['type']}  OUTPUT={oe['type']}  !!")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    INPUT_DEFAULT  = "input/Hotel Options - new design - hand-curated.docx"
    OUTPUT_DEFAULT = "input/Hotel Options - new design - code created.docx"

    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    input_path  = args[0] if len(args) > 0 else INPUT_DEFAULT
    output_path = args[1] if len(args) > 1 else OUTPUT_DEFAULT

    only_page = None
    for a in sys.argv[1:]:
        if a.startswith('--page='):
            only_page = int(a.split('=')[1])
        elif a == '--page' and sys.argv.index(a) + 1 < len(sys.argv):
            only_page = int(sys.argv[sys.argv.index(a) + 1])

    compare_pages(input_path, output_path, only_page)
