import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import src.library.__main__ as cli
from src.library.ingest_core import pilot as pilot_mod
from src.library.ingest_core import plan as plan_mod
from src.library.ingest_core.extract import Extraction
from src.library.ingest_core.pilot import PilotError, run_pilot, select_pilot_files
from src.library.ingest_core.plan import build_plan, load_plan
from src.library.ingest_core.runner import PlanEntry

runner = CliRunner()


def _e(tmp_path, name, folder, fmt="new", size=10):
    p = tmp_path / folder.replace("/", "_") / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return PlanEntry(path=p, folder=folder, order_date=date(2025, 1, 1), fmt=fmt, text_hash=f"h-{name}")


def _synthetic(tmp_path):
    folders = ["Italy", "France", "Japan", "Spain", "Dubai and Abu Dhabi - UAE"]
    plan = []
    for i in range(30):
        plan.append(_e(tmp_path, f"f{i:02d}.docx", folders[i % 5],
                       fmt="old" if i % 7 == 0 else "new", size=10 + i))
    plan.append(_e(tmp_path, "huge.docx", "Spain", size=99999))
    return plan


def test_select_pilot_files_coverage(tmp_path):
    plan = _synthetic(tmp_path)
    a = select_pilot_files(plan, 10)
    assert len(a) <= 10
    assert {e.fmt for e in a} == {"old", "new"}
    assert any(Path(e.path).name == "huge.docx" for e in a)
    assert any(" and " in e.folder for e in a)
    assert len({e.folder for e in a}) >= 2
    assert [e.path for e in a] == [e.path for e in select_pilot_files(plan, 10)]
    assert len(select_pilot_files(plan, 3)) <= 3


def test_build_plan_prefers_library_folder(tmp_path, monkeypatch):
    inp, lib = tmp_path / "in", tmp_path / "lib"
    (lib / "Italy").mkdir(parents=True)
    (lib / "Italy" / "a.pdf").write_bytes(b"old")
    inp.mkdir()
    (inp / "a.pdf").write_bytes(b"new")
    from src.library.ingest_core import ordering

    scan = ordering.FileScan(path=inp / "a.pdf", mtime=date(2025, 1, 1), text_hash="ha",
                             fmt="new", last_day=None, looks_like_aig=True)
    monkeypatch.setattr(plan_mod, "scan_file", lambda p: scan)

    class Boom:
        api_key = "k"

        def complete(self, *a, **k):
            raise AssertionError("classifier must not be called")

    entries = build_plan(inp, lib, Boom(), tmp_path / "out")
    rows = json.loads((tmp_path / "out" / "plan.json").read_text())
    assert rows[0]["folder"] == "Italy"
    assert (tmp_path / "out" / "order_report.md").exists()
    assert [e.folder for e in entries] == ["Italy"]


def test_build_plan_classifies_unknown_with_passed_client(tmp_path, monkeypatch):
    from src.library.ingest_core import ordering

    inp, lib = tmp_path / "in", tmp_path / "lib"
    (lib / "Italy").mkdir(parents=True)
    inp.mkdir()
    (inp / "b.pdf").write_bytes(b"b")
    scan = ordering.FileScan(path=inp / "b.pdf", mtime=date(2025, 1, 1), text_hash="hb",
                             fmt="new", last_day=None, looks_like_aig=True)
    monkeypatch.setattr(plan_mod, "scan_file", lambda p: scan)
    monkeypatch.setattr("src.library.ingester.LibraryIngester._extract_preview",
                        lambda self, p, max_chars=3000: "text")

    class Stub:
        api_key = "k"
        calls = 0

        def complete(self, prompt, **k):
            Stub.calls += 1
            return '{"folder": "Italy"}'

    entries = build_plan(inp, lib, Stub(), tmp_path / "out")
    assert Stub.calls == 1
    assert [e.folder for e in entries] == ["Italy"]


def test_load_plan_skips_and_reflects_edits(tmp_path):
    rows = [
        {"path": "/x/a.pdf", "folder": "Italy", "order_date": "2025-01-02", "basis": "mtime",
         "fmt": "old", "text_hash": "h1", "skipped_reason": None},
        {"path": "/x/b.pdf", "folder": "", "order_date": None, "basis": "format",
         "fmt": "new", "text_hash": "h2", "skipped_reason": "duplicate"},
    ]
    (tmp_path / "plan.json").write_text(json.dumps(rows))
    got = load_plan(tmp_path)
    assert [(e.folder, e.order_date) for e in got] == [("Italy", date(2025, 1, 2))]
    rows[0]["folder"] = "France"
    (tmp_path / "plan.json").write_text(json.dumps(rows))
    assert load_plan(tmp_path)[0].folder == "France"


class Probe:
    def __init__(self, fail=False):
        self.fail = fail
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.cost_usd = 0.0

    def complete(self, *a, **k):
        if self.fail:
            raise RuntimeError("no route")
        return "OK"


def test_pilot_writes_reports_and_no_db(tmp_path, monkeypatch):
    plan = [_e(tmp_path, "a.docx", "Italy", "old"), _e(tmp_path, "b.docx", "France")]
    monkeypatch.setattr(pilot_mod, "extract_file", lambda c, p: Extraction(
        data={"restaurants": [{"name": "R1"}], "attractions": [{"name": "A1"}]}, chunks=1,
        prompt_tokens=150_000 if p.name == "a.docx" else 10, completion_tokens=5, usd=0.5))
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    out = tmp_path / "out"
    run_pilot(plan, ["m1", "m2"], out, clients={"m1": Probe(), "m2": Probe()})
    rep = json.loads((out / "pilot_report.json").read_text())
    assert rep["models"]["m1"]["avg_usd_per_file"] == 0.5
    assert rep["files"][0]["models"]["m1"]["over_100k_prompt"] is True
    md = (out / "pilot_report.md").read_text()
    assert "R1" in md and "A1" in md and "100K" in md
    assert list(db_dir.iterdir()) == []


def test_pilot_probe_failure_cli(tmp_path, monkeypatch):
    plan = [_e(tmp_path, "a.docx", "Italy")]
    (tmp_path / "plan.json").write_text(json.dumps([{
        "path": str(plan[0].path), "folder": "Italy", "order_date": None, "basis": "x",
        "fmt": "new", "text_hash": "h", "skipped_reason": None}]))
    monkeypatch.setattr("src.common.ai_provider.get_ai_client",
                        lambda model=None, **k: Probe(fail=True))
    called = []
    monkeypatch.setattr(pilot_mod, "extract_file", lambda *a: called.append(1))
    res = runner.invoke(cli.app, ["pilot", "--plan", str(tmp_path), "--models", "bad-model",
                                  "--out", str(tmp_path / "o")])
    assert res.exit_code != 0
    out = " ".join(res.output.split())
    assert "bad-model" in out and "no route" in out
    assert not called


def test_probe_failure_raises(tmp_path):
    with pytest.raises(PilotError, match="m1"):
        run_pilot([], ["m1"], tmp_path, clients={"m1": Probe(fail=True)})


def _write_plan(tmp_path, n=2):
    rows = []
    for i in range(n):
        rows.append({"path": str(tmp_path / f"f{i}.docx"), "folder": "Italy", "order_date": "2025-01-01",
                     "basis": "mtime", "fmt": "new", "text_hash": f"h{i}", "skipped_reason": None})
    rows.append({"path": "/x/s.pdf", "folder": "", "order_date": None, "basis": "x", "fmt": "new",
                 "text_hash": "hs", "skipped_reason": "duplicate"})
    d = tmp_path / "plan"
    d.mkdir()
    (d / "plan.json").write_text(json.dumps(rows))
    return d


def test_rebuild_refuses_library_db(tmp_path):
    d = _write_plan(tmp_path)
    for p in ("library_db", "./library_db/"):
        res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", p, "--max-usd", "1"])
        assert res.exit_code != 0
        assert "library_db" in res.output


def test_rebuild_requires_max_usd(tmp_path):
    d = _write_plan(tmp_path)
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(tmp_path / "new")])
    assert res.exit_code != 0
    assert "--max-usd" in res.output
    assert not (tmp_path / "new").exists()


def test_rebuild_dry_run_projection(tmp_path):
    d = _write_plan(tmp_path, 3)
    rep = tmp_path / "pilot_report.json"
    rep.write_text(json.dumps({"models": {"m1": {"avg_usd_per_file": 0.25}}, "files": []}))
    db = tmp_path / "new"
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(db), "--dry-run",
                                  "--estimate-from", str(rep), "--model", "m1"])
    assert res.exit_code == 0, res.output
    assert "Files to extract: 3" in res.output
    assert "$0.75" in res.output
    assert not db.exists()


class _Client:
    model = "stub-model"
    cost_usd = 0.0
    usage = {"prompt_tokens": 0, "completion_tokens": 0}


def test_rebuild_happy_path(tmp_path, monkeypatch):
    d = _write_plan(tmp_path, 2)
    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: _Client())
    from src.library.ingest_core import runner as runner_mod

    monkeypatch.setattr(runner_mod, "extract_file", lambda c, p: Extraction(
        data={"covered_cities": ["Rome"], "city_countries": {"Rome": "Italy"},
              "restaurants": [{"name": f"R-{Path(p).stem}", "city": "Rome", "hours": "9"}]},
        chunks=1, prompt_tokens=1, completion_tokens=1, usd=0.0))
    db = tmp_path / "new"
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(db), "--max-usd", "5",
                                  "--workers", "1"])
    assert res.exit_code == 0, res.output
    assert (db / "Rome.json").exists()
    assert (db / "_ingest_log" / "ingest_log.jsonl").exists()
    idx = json.loads((db / "_index.json").read_text())
    assert len(idx["_processed_files"]) == 2


def test_rebuild_ctrl_c(tmp_path, monkeypatch):
    d = _write_plan(tmp_path, 1)
    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: _Client())
    from src.library.ingest_core import runner as runner_mod

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_mod, "run_ingest", boom)
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(tmp_path / "new"),
                                  "--max-usd", "5"])
    assert res.exit_code == 130
    assert "Progress is saved; re-run the same command to resume." in res.output


# ---- fix round 1 ----
def _aig_scan(path, h):
    from src.library.ingest_core import ordering

    return ordering.FileScan(path=path, mtime=date(2025, 1, 1), text_hash=h, fmt="new",
                             last_day=None, looks_like_aig=True)


class _Cls:
    api_key = "k"

    def __init__(self, folder="Italy", fail=False):
        self.folder, self.fail, self.calls = folder, fail, 0

    def complete(self, prompt, **k):
        self.calls += 1
        if self.fail:
            raise AssertionError("classifier must not be called")
        return json.dumps({"folder": self.folder}) if self.folder else "garbage"


def _setup(tmp_path, monkeypatch):
    inp, lib = tmp_path / "in", tmp_path / "lib"
    (lib / "Italy").mkdir(parents=True)
    inp.mkdir()
    monkeypatch.setattr(plan_mod, "scan_file", lambda p: _aig_scan(p, "h-" + p.name))
    monkeypatch.setattr("src.library.ingester.LibraryIngester._extract_preview",
                        lambda self, p, max_chars=3000: "text")
    return inp, lib


def test_replan_keeps_hand_edits_and_classifies_only_new(tmp_path, monkeypatch):
    inp, lib = _setup(tmp_path, monkeypatch)
    (inp / "a.pdf").write_bytes(b"a")
    out = tmp_path / "out"
    build_plan(inp, lib, _Cls("Italy"), out)
    rows = json.loads((out / "plan.json").read_text())
    rows[0]["folder"] = "Hand Edited"
    (out / "plan.json").write_text(json.dumps(rows))

    build_plan(inp, lib, _Cls(fail=True), out)
    assert json.loads((out / "plan.json").read_text())[0]["folder"] == "Hand Edited"

    (inp / "b.pdf").write_bytes(b"b")
    c = _Cls("France")
    build_plan(inp, lib, c, out)
    got = {Path(r["path"]).name: r["folder"] for r in json.loads((out / "plan.json").read_text())}
    assert c.calls == 1
    assert got == {"a.pdf": "Hand Edited", "b.pdf": "France"}


def test_no_folder_visible_and_rescuable(tmp_path, monkeypatch):
    inp, lib = _setup(tmp_path, monkeypatch)
    (inp / "a.pdf").write_bytes(b"a")
    out = tmp_path / "out"
    entries = build_plan(inp, lib, _Cls(folder=None), out)
    assert entries == []
    rows = json.loads((out / "plan.json").read_text())
    assert rows[0]["skipped_reason"] == "no_folder"
    assert "## Needs a folder (edit plan.json)" in (out / "order_report.md").read_text()
    assert "- a.pdf" in (out / "order_report.md").read_text().split("## Needs a folder")[1]
    # (c) hand-filled folder is processable; other reasons stay skipped
    rows[0]["folder"] = "Italy"
    rows.append({**rows[0], "path": "/x/d.pdf", "skipped_reason": "duplicate", "folder": "Italy"})
    (out / "plan.json").write_text(json.dumps(rows))
    assert [e.folder for e in load_plan(out)] == ["Italy"]
    # (a) CLI lists them
    rows[0]["folder"] = ""
    (out / "plan.json").write_text(json.dumps(rows[:1]))
    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: _Cls(folder=None))
    res = runner.invoke(cli.app, ["plan", "--input", str(inp), "--library", str(lib), "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "1 file(s) have no folder" in res.output and "a.pdf" in res.output


def test_load_plan_invalid_entries(tmp_path):
    from src.library.ingest_core.plan import PlanError

    base = {"path": "/x/a.pdf", "folder": "Italy", "order_date": None, "basis": "m", "fmt": "new",
            "text_hash": "h", "skipped_reason": None}
    for bad, why in (({k: v for k, v in base.items() if k != "fmt"}, "missing"),
                     ({**base, "folder": ""}, "folder is empty")):
        (tmp_path / "plan.json").write_text(json.dumps([bad]))
        with pytest.raises(PlanError, match=r"plan.json entry 0 \(/x/a.pdf\) is invalid: " + why):
            load_plan(tmp_path)
    (tmp_path / "plan.json").write_text(json.dumps([{**base, "folder": ""}]))
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(tmp_path), "--db", str(tmp_path / "n"),
                                  "--max-usd", "1"])
    assert res.exit_code == 1 and "is invalid" in res.output and "Traceback" not in res.output


def test_rebuild_prints_model_count_ceiling_before_run(tmp_path, monkeypatch):
    d = _write_plan(tmp_path, 2)

    class C(_Client):
        model = "env-model"

    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: C())
    from src.library.ingest_core import runner as runner_mod

    seen = {}

    def spy(*a, **k):
        seen["out"] = capture["fn"]()
        raise KeyboardInterrupt

    capture = {}
    monkeypatch.setattr(runner_mod, "run_ingest", spy)
    # CliRunner buffers output; capture what has been printed so far via console.print
    printed = []
    real = cli.console.print
    monkeypatch.setattr(cli.console, "print", lambda *a, **k: (printed.append(" ".join(map(str, a))), real(*a, **k)))
    capture["fn"] = lambda: "\n".join(printed)
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(tmp_path / "n"), "--max-usd", "5"])
    out = seen["out"]
    assert "env-model (default from the environment" in out
    assert "Files to process: 2" in out
    assert "$5.00" in out
    assert res.exit_code == 130


def test_rebuild_dry_run_needs_estimate_and_model(tmp_path):
    d = _write_plan(tmp_path)
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(tmp_path / "n"), "--dry-run"])
    assert res.exit_code == 1 and "--estimate-from" in res.output and "--model" in res.output


def test_rebuild_rejects_nonpositive_max_usd(tmp_path):
    d = _write_plan(tmp_path)
    for v in ("0", "-1"):
        res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(tmp_path / "n"),
                                      "--max-usd", v])
        assert res.exit_code == 1 and "greater than 0" in res.output


def test_pilot_single_file_error_recorded(tmp_path, monkeypatch):
    plan = [_e(tmp_path, "a.docx", "Italy"), _e(tmp_path, "b.docx", "France")]

    def fake(c, p):
        if p.name == "a.docx":
            raise RuntimeError("boom")
        return Extraction(data={"restaurants": [{"name": "R"}]}, chunks=1, prompt_tokens=1,
                          completion_tokens=1, usd=0.1)

    monkeypatch.setattr(pilot_mod, "extract_file", fake)
    out = tmp_path / "out"
    run_pilot(plan, ["m1"], out, clients={"m1": Probe()})
    rep = json.loads((out / "pilot_report.json").read_text())
    assert "RuntimeError: boom" in rep["files"][0]["models"]["m1"]["error"]
    assert rep["files"][1]["models"]["m1"]["failed"] is False
    assert "boom" in (out / "pilot_report.md").read_text()


# --- B3: classification errors are counted and shown ---------------------

def _classify_setup(tmp_path, monkeypatch, names=("b.pdf", "c.pdf")):
    from src.library.ingest_core import ordering

    inp, lib = tmp_path / "in", tmp_path / "lib"
    (lib / "Italy").mkdir(parents=True)
    inp.mkdir()
    for n in names:
        (inp / n).write_bytes(n.encode())
    monkeypatch.setattr(plan_mod, "scan_file", lambda p: ordering.FileScan(
        path=p, mtime=date(2025, 1, 1), text_hash=f"h-{p.name}", fmt="new", last_day=None, looks_like_aig=True))
    monkeypatch.setattr("src.library.ingester.LibraryIngester._extract_preview",
                        lambda self, p, max_chars=3000: "text")
    return inp, lib


def test_build_plan_records_classification_failures(tmp_path, monkeypatch):
    inp, lib = _classify_setup(tmp_path, monkeypatch)

    class Raises:
        api_key = "k"

        def complete(self, prompt, **k):
            raise RuntimeError("gateway 502")

    entries = build_plan(inp, lib, Raises(), tmp_path / "out")
    assert entries == []
    rows = json.loads((tmp_path / "out" / "plan.json").read_text())
    assert [r["skipped_reason"] for r in rows] == ["no_folder", "no_folder"]
    assert all("gateway 502" in r["classify_error"] for r in rows)
    assert "Classification FAILED for 2 file(s)" in (tmp_path / "out" / "order_report.md").read_text()


def test_empty_answer_is_no_folder_but_not_a_failure(tmp_path, monkeypatch):
    inp, lib = _classify_setup(tmp_path, monkeypatch, names=("b.pdf",))

    class Empty:
        api_key = "k"

        def complete(self, prompt, **k):
            return '{"folder": ""}'

    build_plan(inp, lib, Empty(), tmp_path / "out")
    row = json.loads((tmp_path / "out" / "plan.json").read_text())[0]
    assert row["skipped_reason"] == "no_folder" and "classify_error" not in row


def test_plan_cli_prints_prominent_classification_block(tmp_path, monkeypatch):
    inp, lib = _classify_setup(tmp_path, monkeypatch)

    class Raises:
        api_key = "k"

        def complete(self, prompt, **k):
            raise RuntimeError("gateway 502")

    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: Raises())
    res = runner.invoke(cli.app, ["plan", "--input", str(inp), "--library", str(lib),
                                  "--out", str(tmp_path / "out")])
    out = " ".join(res.output.split())
    assert res.exit_code == 0, res.output
    assert "2 files could not be classified (first error: RuntimeError: gateway 502) - these are marked no_folder" in out


def test_ingester_classify_file_still_swallows_errors(tmp_path, monkeypatch):
    from src.library.ingester import LibraryIngester

    monkeypatch.setattr(LibraryIngester, "_extract_preview", lambda self, p, max_chars=3000: "t")
    ing = LibraryIngester(tmp_path, api_key="k")

    class Raises:
        def complete(self, *a, **k):
            raise RuntimeError("down")

    ing.client = Raises()
    assert ing._classify_file(tmp_path / "x.pdf", ["Italy"]) is None


# --- B4: live-library guard covers paths inside library_db ---------------

def test_is_live_library_refuses_paths_inside(tmp_path):
    root = Path(cli.__file__).resolve().parents[2] / "library_db"
    assert cli._is_live_library(Path("library_db"))
    assert cli._is_live_library(root / "new")
    assert cli._is_live_library(Path("library_db/new/deeper"))
    assert not cli._is_live_library(tmp_path / "library_db_new")
    assert not cli._is_live_library(root.parent / "library_db_new")


def test_rebuild_refuses_path_inside_library_db(tmp_path):
    d = _write_plan(tmp_path)
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", "library_db/new", "--max-usd", "1"])
    assert res.exit_code != 0 and "library_db" in res.output
    assert not Path("library_db/new").exists()


def test_pilot_report_carries_extraction_error_reason(tmp_path, monkeypatch):
    from src.library.ingest_core.extract import ExtractionError

    plan = [_e(tmp_path, "a.docx", "Italy")]

    def boom(c, p):
        raise ExtractionError("truncated: a.docx hit the output limit")

    monkeypatch.setattr(pilot_mod, "extract_file", boom)
    out = tmp_path / "out"
    run_pilot(plan, ["m1"], out, clients={"m1": Probe()})
    rep = json.loads((out / "pilot_report.json").read_text())
    assert "truncated" in rep["files"][0]["models"]["m1"]["error"]


def test_pilot_cli_and_rebuild_use_ingest_client(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("src.common.ai_provider.get_ai_client",
                        lambda **k: seen.append(k) or Probe())
    plan = [_e(tmp_path, "a.docx", "Italy")]
    (tmp_path / "plan.json").write_text(json.dumps([{
        "path": str(plan[0].path), "folder": "Italy", "order_date": None, "basis": "x",
        "fmt": "new", "text_hash": "h", "skipped_reason": None}]))
    monkeypatch.setattr(pilot_mod, "extract_file", lambda *a: None)
    runner.invoke(cli.app, ["pilot", "--plan", str(tmp_path), "--models", "m1", "--out", str(tmp_path / "o")])
    assert seen and seen[0]["timeout"] == 600.0 and seen[0]["max_retries"] == 1 and seen[0]["model"] == "m1"
