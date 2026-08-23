"""Integration tests for src/aig/prep.py against the 4 real BVM input files.

Tests in this module touch the actual DOCX files in input/aigbootstrap/ and
the real library DB.  They are skipped when those paths are absent so the
suite stays green in clean CI checkouts.
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO = Path(__file__).parent.parent.parent
_INPUT = _REPO / "input" / "aigbootstrap"
_DB = _REPO / "library_db"

_FILES = {
    "bhushan": _INPUT / "Bhushan London-notes for aig.docx",
    "naren":   _INPUT / "Naren - Peru- Service_Vouhcer.docx",
    "peter":   _INPUT / "Service_Voucher_Peter_Bali.docx",
    "silky":   _INPUT / "Silky Mussoorie_notes for aig.docx",
}

_db_available = _DB.exists() and (_DB / "_index.json").exists()


def _skip_unless(key: str):
    """Pytest mark: skip if the named file doesn't exist."""
    return pytest.mark.skipif(
        not _FILES[key].exists(),
        reason=f"{_FILES[key].name} not present",
    )


# ---------------------------------------------------------------------------
# _extract_from_docx unit-level tests (no DB needed)
# ---------------------------------------------------------------------------

@_skip_unless("bhushan")
def test_bhushan_extraction():
    """Bhushan notes file: name from filename, London as city."""
    from src.aig.prep import _extract_from_docx
    r = _extract_from_docx(_FILES["bhushan"])
    assert r.get("client_name") == "Bhushan"
    assert "London" in r.get("cities", [])


@_skip_unless("naren")
def test_naren_extraction():
    """Naren service voucher: name from Guest Name, cities from City table."""
    from src.aig.prep import _extract_from_docx
    r = _extract_from_docx(_FILES["naren"])
    assert r.get("client_name") == "Naren"
    cities = r.get("cities", [])
    assert "Lima" in cities
    assert "Cusco" in cities
    assert r.get("trip_start_date") == "13 Aug 2026"
    assert r.get("trip_end_date") == "22 Aug 2026"


@_skip_unless("peter")
def test_peter_extraction():
    """Peter service voucher: name from MR. prefix, cities from CITY_NAME table."""
    from src.aig.prep import _extract_from_docx
    r = _extract_from_docx(_FILES["peter"])
    assert "Peter" in (r.get("client_name") or "")
    cities = r.get("cities", [])
    assert any(c in cities for c in ("Ubud", "Sanur"))
    hotels = r.get("hotels", {})
    assert any("Mayura" in v or "Ubud" in v for v in hotels.values())
    assert r.get("trip_start_date") == "13 Jul 2026"
    assert r.get("trip_end_date") == "16 Jul 2026"


@_skip_unless("silky")
def test_silky_extraction():
    """Silky notes file: name from filename, both cities from title."""
    from src.aig.prep import _extract_from_docx
    r = _extract_from_docx(_FILES["silky"])
    assert r.get("client_name") == "Silky"
    cities = r.get("cities", [])
    assert "Dehradun" in cities
    assert "Mussoorie" in cities


# ---------------------------------------------------------------------------
# extract_trip_context full-pipeline tests
# ---------------------------------------------------------------------------

@_skip_unless("bhushan")
def test_bhushan_prep_context():
    from src.aig.prep import extract_trip_context
    ctx = extract_trip_context(_FILES["bhushan"])
    assert ctx.client_name == "Bhushan"
    assert "London" in ctx.cities
    assert ctx.destination_label != ""


@_skip_unless("naren")
def test_naren_prep_context():
    from src.aig.prep import extract_trip_context
    ctx = extract_trip_context(_FILES["naren"])
    assert ctx.client_name == "Naren"
    assert "Lima" in ctx.cities
    assert ctx.date_range != ""


@_skip_unless("peter")
def test_peter_prep_context():
    from src.aig.prep import extract_trip_context
    ctx = extract_trip_context(_FILES["peter"])
    assert "Peter" in ctx.client_name
    assert ctx.cities  # at least one city
    assert ctx.hotels  # at least one hotel


@_skip_unless("silky")
def test_silky_prep_context():
    from src.aig.prep import extract_trip_context
    ctx = extract_trip_context(_FILES["silky"])
    assert ctx.client_name == "Silky"
    assert "Dehradun" in ctx.cities
    assert "Mussoorie" in ctx.cities


# ---------------------------------------------------------------------------
# run_prep end-to-end: writes two files with correct names and content
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _FILES["bhushan"].exists() or not _db_available,
    reason="bhushan.docx or library_db not present",
)
def test_run_prep_bhushan(tmp_path):
    from src.aig.prep import run_prep
    ctx_path, prof_path = run_prep(_FILES["bhushan"], _DB, output_dir=tmp_path)
    assert ctx_path.exists()
    assert prof_path.exists()
    assert "Bhushan" in ctx_path.name
    assert "London" in ctx_path.name or "London" in ctx_path.read_text(encoding="utf-8")
    assert "Bhushan" in prof_path.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not _FILES["naren"].exists() or not _db_available,
    reason="naren.docx or library_db not present",
)
def test_run_prep_naren(tmp_path):
    from src.aig.prep import run_prep
    ctx_path, prof_path = run_prep(_FILES["naren"], _DB, output_dir=tmp_path)
    ctx_text = ctx_path.read_text(encoding="utf-8")
    prof_text = prof_path.read_text(encoding="utf-8")
    assert "Naren" in prof_text
    assert "Lima" in ctx_text or "## Lima" in ctx_text


@pytest.mark.skipif(
    not _FILES["peter"].exists() or not _db_available,
    reason="peter.docx or library_db not present",
)
def test_run_prep_peter(tmp_path):
    from src.aig.prep import run_prep
    ctx_path, prof_path = run_prep(_FILES["peter"], _DB, output_dir=tmp_path)
    prof_text = prof_path.read_text(encoding="utf-8")
    assert "Peter" in prof_text
    assert ctx_path.exists()


@pytest.mark.skipif(
    not _FILES["silky"].exists() or not _db_available,
    reason="silky.docx or library_db not present",
)
def test_run_prep_silky(tmp_path):
    from src.aig.prep import run_prep
    ctx_path, prof_path = run_prep(_FILES["silky"], _DB, output_dir=tmp_path)
    ctx_text = ctx_path.read_text(encoding="utf-8")
    prof_text = prof_path.read_text(encoding="utf-8")
    assert "Silky" in prof_text
    assert "Dehradun" in ctx_text or "Mussoorie" in ctx_text
