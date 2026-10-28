import json
import threading
import zipfile
from datetime import date
from pathlib import Path

import pytest

from src.library.ingest_core import IngestReport, PlanEntry, run_ingest
from src.library.ingest_core import runner as runner_mod
from src.library.ingest_core.extract import Extraction
from src.library.ui.services.db_service import LibraryDBService


class StubClient:
    def __init__(self, cost=0.0):
        self.cost_usd = cost
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}


def _entry(tmp_path, name, d=date(2025, 1, 1), fmt="new", folder="italy", h=None):
    return PlanEntry(path=tmp_path / name, folder=folder, order_date=d, fmt=fmt,
                     text_hash=h or f"hash-{name}")


def _data(name, hours="9-5", city="Rome"):
    return {"covered_cities": [city], "city_countries": {city: "Italy"},
            "restaurants": [{"name": name, "city": city, "hours": hours}]}


class FakeExtractor:
    """Stand-in for extract_file. ``results`` maps file name -> data, None or exception."""

    def __init__(self, results, client, usd_each=0.0, waits=None):
        self.results = results
        self.client = client
        self.usd_each = usd_each
        self.waits = waits or {}
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, client, path):
        name = Path(path).name
        with self.lock:
            self.calls.append(name)
        if name in self.waits:
            assert self.waits[name].wait(5), "timed out waiting"
        with self.lock:
            if self.client.cost_usd is not None:
                self.client.cost_usd += self.usd_each
        r = self.results[name]
        if isinstance(r, BaseException):
            raise r
        if r is None:
            return None
        return Extraction(data=r, chunks=1, prompt_tokens=100, completion_tokens=40,
                          usd=self.usd_each)


def _patch(monkeypatch, fake):
    monkeypatch.setattr(runner_mod, "extract_file", fake)


def _log_lines(tmp_path):
    raw = (tmp_path / "logs" / "ingest_log.jsonl").read_text().splitlines()
    return [json.loads(line) for line in raw]


# (a)
def test_merge_in_plan_order_even_when_second_finishes_first(tmp_path, memory_db, monkeypatch):
    client = StubClient()
    b_done = threading.Event()
    fake = FakeExtractor({"a.docx": _data("Roscioli", "1"), "b.docx": _data("Roscioli", "2"),
                          "c.docx": _data("Roscioli", "3")}, client, waits={"a.docx": b_done})

    def fake_call(c, path):
        r = FakeExtractor.__call__(fake, c, path)
        if Path(path).name == "b.docx":
            b_done.set()
        return r

    _patch(monkeypatch, fake_call)
    merged = []
    real_merge = runner_mod.merge_extraction

    def spy(db, data, meta):
        merged.append(meta.source_file)
        return real_merge(db, data, meta)

    monkeypatch.setattr(runner_mod, "merge_extraction", spy)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx", "c.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=3)
    assert merged == ["italy/a.docx", "italy/b.docx", "italy/c.docx"]
    assert report.processed == merged
    assert memory_db.get_city_data("Rome")["restaurants"][0]["hours"] == "3"


# (b)
def test_empty_extraction_fails_writes_nothing_next_runs(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": None, "b.docx": {"covered_cities": [], "restaurants": []},
                          "c.docx": _data("Roscioli")}, client)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx", "c.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=1)
    assert [f for f, _ in report.failed] == ["italy/a.docx", "italy/b.docx"]
    assert report.processed == ["italy/c.docx"]
    shard = memory_db.get_city_data("Rome")
    assert shard["source_files"] == ["italy/c.docx"]
    processed = LibraryDBService(memory_backend)._index["_processed_files"]
    assert list(processed) == ["italy/c.docx"]


# (c)
def test_rerun_same_plan_processes_nothing(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": _data("Armando")}, client)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx")]
    run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=2)
    before = memory_backend.files["Rome.json"]
    fake.calls.clear()

    db2 = LibraryDBService(memory_backend)
    report = run_ingest(plan, db2, client, log_dir=tmp_path / "logs", workers=2)
    assert report.processed == []
    assert report.skipped == [("italy/a.docx", "already_processed"),
                              ("italy/b.docx", "already_processed")]
    assert fake.calls == []
    assert memory_backend.files["Rome.json"] == before


def test_changed_hash_is_reprocessed(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli")}, client)
    _patch(monkeypatch, fake)
    run_ingest([_entry(tmp_path, "a.docx", h="h1")], memory_db, client, log_dir=tmp_path / "logs")
    report = run_ingest([_entry(tmp_path, "a.docx", h="h2")], LibraryDBService(memory_backend),
                        client, log_dir=tmp_path / "logs")
    assert report.processed == ["italy/a.docx"]


# (d)
def test_merge_exception_on_second_file_records_only_first(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": _data("Armando")}, client)
    _patch(monkeypatch, fake)
    real_merge = runner_mod.merge_extraction

    def boom(db, data, meta):
        if meta.source_file == "italy/b.docx":
            raise RuntimeError("merge exploded")
        return real_merge(db, data, meta)

    monkeypatch.setattr(runner_mod, "merge_extraction", boom)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=1)
    processed = LibraryDBService(memory_backend)._index["_processed_files"]
    assert list(processed) == ["italy/a.docx"]
    assert report.failed == [("italy/b.docx", "RuntimeError: merge exploded")]
    assert memory_db.get_folder_coverage() == {"italy": ["Rome"]}


def test_malformed_output_on_file2_does_not_stop_file3(tmp_path, memory_db, monkeypatch):
    client = StubClient()
    # data that is not a dict makes clean_extraction raise
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": ["not", "a", "dict"],
                          "c.docx": _data("Armando"), "d.docx": ValueError("bad json")}, client)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx", "c.docx", "d.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=2)
    assert report.processed == ["italy/a.docx", "italy/c.docx"]
    assert [f for f, _ in report.failed] == ["italy/b.docx", "italy/d.docx"]
    assert "ValueError: bad json" in report.failed[1][1]
    lines = {line["file"]: line for line in _log_lines(tmp_path)}
    assert lines["italy/b.docx"]["status"] == "failed"
    assert lines["italy/b.docx"]["error"]
    assert lines["italy/d.docx"]["error"] == "ValueError: bad json"


# (e)
def test_ceiling_stops_after_file_that_crosses_it(tmp_path, memory_db, monkeypatch):
    client = StubClient(cost=0.0)
    names = ("a.docx", "b.docx", "c.docx", "d.docx")
    fake = FakeExtractor({n: _data(n) for n in names}, client, usd_each=1.0)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in names]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=1, max_usd=1.5)
    assert report.processed == ["italy/a.docx", "italy/b.docx"]
    assert fake.calls == ["a.docx", "b.docx"]
    assert report.stopped_on_ceiling is True
    assert report.cost_usd == 2.0
    assert ("italy/c.docx", "cost_ceiling") in report.skipped


def test_ceiling_overshoot_bounded_by_workers(tmp_path, memory_db, monkeypatch):
    client = StubClient(cost=0.0)
    names = [f"f{i}.docx" for i in range(10)]
    fake = FakeExtractor({n: _data(n) for n in names}, client, usd_each=1.0)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in names]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=3, max_usd=0.5)
    assert 1 <= len(fake.calls) <= 3
    assert len(report.processed) == len(fake.calls)
    assert report.stopped_on_ceiling is True


# (f)
def test_v2_generated_file_skipped(tmp_path, memory_db, monkeypatch):
    p = tmp_path / "v2.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("docProps/custom.xml",
                   '<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/custom-properties"><property fmtid="{x}" pid="2" '
                   'name="bvbm_run_id"><lpwstr>abc</lpwstr></property></Properties>')
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli")}, client)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, "v2.docx"), _entry(tmp_path, "a.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs")
    assert report.skipped == [("italy/v2.docx", "v2_generated")]
    assert fake.calls == ["a.docx"]


# (g)
def test_unpriced_model_with_max_usd_raises(tmp_path, memory_db, monkeypatch):
    client = StubClient(cost=None)
    fake = FakeExtractor({"a.docx": _data("Roscioli")}, client)
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError, match="no known price"):
        run_ingest([_entry(tmp_path, "a.docx")], memory_db, client,
                   log_dir=tmp_path / "logs", max_usd=5.0)
    assert fake.calls == []
    assert not (tmp_path / "logs").exists()


def test_unpriced_model_without_ceiling_runs(tmp_path, memory_db, monkeypatch):
    client = StubClient(cost=None)
    fake = FakeExtractor({"a.docx": _data("Roscioli")}, client)
    _patch(monkeypatch, fake)
    report = run_ingest([_entry(tmp_path, "a.docx")], memory_db, client, log_dir=tmp_path / "logs")
    assert report.processed == ["italy/a.docx"]
    assert report.cost_usd is None


def test_keyboard_interrupt_saves_index_and_propagates(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": KeyboardInterrupt(),
                          "c.docx": _data("Armando")}, client)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx", "c.docx")]
    with pytest.raises(KeyboardInterrupt):
        run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=1)
    index = LibraryDBService(memory_backend)._index
    assert list(index["_processed_files"]) == ["italy/a.docx"]
    assert index["_folder_coverage"] == {"italy": ["Rome"]}
    assert "c.docx" not in fake.calls


def test_log_has_one_json_line_per_file(tmp_path, memory_db, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": None,
                          "c.docx": {**_data("Armando"),
                                     "attractions": [{"name": "⚠ VERIFY x", "city": "Rome"}]}},
                         client, usd_each=0.25)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx", "c.docx")]
    run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=1)
    run_ingest(plan[:1], memory_db, client, log_dir=tmp_path / "logs", workers=1)
    lines = _log_lines(tmp_path)
    assert [(l["file"], l["status"]) for l in lines] == [
        ("italy/a.docx", "processed"), ("italy/b.docx", "failed"),
        ("italy/c.docx", "processed"), ("italy/a.docx", "skipped")]
    keys = {"file", "status", "reason", "order_date", "fmt", "stats", "dropped",
            "prompt_tokens", "completion_tokens", "usd", "error"}
    assert all(set(l) == keys for l in lines)
    a = lines[0]
    assert a["order_date"] == "2025-01-01" and a["fmt"] == "new"
    assert a["prompt_tokens"] == 100 and a["completion_tokens"] == 40 and a["usd"] == 0.25
    assert a["stats"]["added"] == 1 and a["stats"]["by_city"]["Rome"]["added"] == 1
    assert lines[2]["dropped"][0]["reason"] == "marker"
    assert lines[3]["reason"] == "already_processed"


def test_workers_gt_1_logs_none_token_figures(tmp_path, memory_db, monkeypatch):
    client = StubClient()
    fake = FakeExtractor({"a.docx": _data("Roscioli"), "b.docx": _data("Armando")},
                         client, usd_each=0.25)
    _patch(monkeypatch, fake)
    plan = [_entry(tmp_path, n) for n in ("a.docx", "b.docx")]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", workers=2)
    lines = _log_lines(tmp_path)
    assert all(l["prompt_tokens"] is None and l["completion_tokens"] is None and l["usd"] is None
               for l in lines)
    assert report.cost_usd == 0.5


def test_processed_file_record_and_checkpoints(tmp_path, memory_db, memory_backend, monkeypatch):
    client = StubClient()
    names = [f"f{i}.docx" for i in range(5)]
    fake = FakeExtractor({n: _data(f"R{n}", hours=n[1]) for n in names}, client)
    _patch(monkeypatch, fake)
    saves = []
    real_save = memory_db.save_index
    monkeypatch.setattr(memory_db, "save_index", lambda: (saves.append(1), real_save()))
    plan = [_entry(tmp_path, n) for n in names]
    report = run_ingest(plan, memory_db, client, log_dir=tmp_path / "logs", checkpoint_every=2)
    assert isinstance(report, IngestReport)
    assert len(report.processed) == 5
    assert len(saves) == 3  # after files 2 and 4, plus the final one
    rec = LibraryDBService(memory_backend)._index["_processed_files"]["italy/f0.docx"]
    assert rec["text_hash"] == "hash-f0.docx"
    assert rec["order_date"] == "2025-01-01"
    assert rec["fmt"] == "new" and rec["folder"] == "italy"
    assert rec["covered_cities"] == ["Rome"]
    assert rec["processed_at"].endswith("+00:00")
    assert [r["hours"] for r in memory_db.get_city_data("Rome")["restaurants"]] == ["0", "1", "2", "3", "4"]


def test_has_content_needs_a_real_item():
    from src.library.ingest_core.runner import has_content

    assert not has_content({"covered_cities": ["Rome"]})
    assert not has_content({"covered_cities": ["Rome"], "restaurants": [], "country_content": [{"country": "Italy"}]})
    assert has_content({"restaurants": [{"name": "X"}]})
    assert has_content({"country_content": [{"country": "Italy", "tipping": [{"tip": "t"}]}]})


def test_covered_cities_only_file_is_failed_as_empty(tmp_path, memory_db, monkeypatch):
    client = StubClient()
    _patch(monkeypatch, FakeExtractor({"a.docx": {"covered_cities": ["Rome"]}}, client))
    report = run_ingest([_entry(tmp_path, "a.docx")], memory_db, client, log_dir=tmp_path / "logs", workers=1)
    assert report.processed == [] and [f for f, _ in report.failed] == ["italy/a.docx"]


def test_extraction_error_reason_reaches_failed_and_log(tmp_path, memory_db, monkeypatch):
    from src.library.ingest_core.extract import ExtractionError

    client = StubClient()
    _patch(monkeypatch, FakeExtractor({"a.docx": ExtractionError("truncated: a.docx hit the output limit")}, client))
    report = run_ingest([_entry(tmp_path, "a.docx")], memory_db, client, log_dir=tmp_path / "logs", workers=1)
    assert "truncated" in report.failed[0][1]
    line = json.loads((tmp_path / "logs" / "ingest_log.jsonl").read_text().splitlines()[0])
    assert line["status"] == "failed" and "truncated" in line["error"]


def test_max_output_tokens_reaches_extract_file(tmp_path, memory_db, monkeypatch):
    seen = []

    def fake(client, path, max_output_tokens=32000):
        seen.append(max_output_tokens)
        return Extraction(data=_data("X"), chunks=1, prompt_tokens=1, completion_tokens=1, usd=0.0)

    monkeypatch.setattr(runner_mod, "extract_file", fake)
    run_ingest([_entry(tmp_path, "a.pdf")], memory_db, StubClient(), log_dir=tmp_path / "logs",
               workers=1, max_output_tokens=64000)
    assert seen == [64000]


def test_default_max_output_tokens_keeps_two_arg_stubs_working(tmp_path, memory_db, monkeypatch):
    fake = FakeExtractor({"a.pdf": _data("X")}, StubClient())
    _patch(monkeypatch, fake)  # FakeExtractor.__call__ takes (client, path) only
    report = run_ingest([_entry(tmp_path, "a.pdf")], memory_db, StubClient(), log_dir=tmp_path / "logs",
                        workers=1)
    assert len(report.processed) == 1
