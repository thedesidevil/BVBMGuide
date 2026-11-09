import importlib.util
import shutil
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "preview_guide", Path(__file__).resolve().parents[2] / "scripts" / "preview_guide.py")
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)


def test_missing_paths_give_clear_errors(tmp_path):
    with pytest.raises(pg.PreviewError, match="not found"):
        pg.find_docx(str(tmp_path / "nope.docx"))
    with pytest.raises(pg.PreviewError, match="run 'nope'"):
        pg.find_docx("nope", str(tmp_path))
    assert pg.main(["nope", "--data-root", str(tmp_path)]) == 1


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("pdftoppm")),
                    reason="soffice/pdftoppm missing")
def test_preview_makes_pdf_and_png(tmp_path):
    import docx
    d = docx.Document()
    d.add_paragraph("Hello preview")
    src = tmp_path / "guide.docx"
    d.save(src)
    n = pg.preview(src, tmp_path / "preview", 40)
    assert n >= 1
    assert (tmp_path / "preview" / "guide.pdf").is_file()
    assert (tmp_path / "preview" / "page-01.png").is_file()
