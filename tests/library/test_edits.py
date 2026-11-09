import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.library import __main__ as cli
from src.library.ingest_core.edits import backup_library, build_blocklist, write_edit_candidates
from src.library.ingest_core.identity import item_key

runner = CliRunner()


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    db = repo / "library_db"
    _write(db / "Cairns.json", {"restaurants": [{"name": "Alpha"}, {"name": "Beta"}], "attractions": []})
    _write(db / "_country" / "Peru.json", {"tipping": [{"tip": "Tip 10%"}, {"tip": "Round up"}]})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    first = _git(repo, "rev-parse", "HEAD")
    _write(db / "Cairns.json", {"restaurants": [{"name": "Alpha"}], "attractions": []})
    _write(db / "_country" / "Peru.json", {"tipping": [{"tip": "Round up"}]})
    _git(repo, "commit", "-qam", "removed")
    return repo, first, _git(repo, "rev-parse", "HEAD")


def test_blocklist_from_git(tmp_path):
    repo, first, second = _repo(tmp_path)
    got = build_blocklist(tmp_path / "missing_audit.json", second, repo)
    assert {"city": "Cairns", "list": "restaurants", "key": "beta"} in got
    assert {"city": "_country/Peru", "list": "tipping", "key": item_key("tipping", {"tip": "Tip 10%"})} in got
    assert len(got) == 2


def test_blocklist_commit_without_parent(tmp_path):
    repo, first, _ = _repo(tmp_path)
    assert build_blocklist(tmp_path / "nope.json", first, repo) == []


def test_blocklist_audit_delete_and_dedupe(tmp_path):
    repo, first, second = _repo(tmp_path)
    audit = tmp_path / "audit.json"
    _write(audit, [
        {"action": "delete", "category": "restaurants", "city": "Cairns", "item_name": "Beta",
         "item_snapshot": {"name": "Beta"}},
        {"action": "delete", "category": "souvenirs", "city": "Rome", "item_name": "Mug"},
        {"action": "add", "category": "restaurants", "city": "Rome", "item_name": "X"},
        {"action": "delete", "category": "bogus", "city": "Rome", "item_name": "Y"},
    ])
    got = build_blocklist(audit, second, repo)
    assert {"city": "Rome", "list": "souvenirs", "key": "mug"} in got
    assert sum(1 for e in got if e["city"] == "Cairns") == 1
    assert len(got) == 3


def test_edit_candidates(tmp_path):
    repo, first, second = _repo(tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "Cairns.json", {"restaurants": [
        {"name": "Alpha", "hours": "9", "_source_file": "a.pdf"},
        {"name": "Beta", "_source_file": "a.pdf"},
        {"name": "Gamma", "hours": "old", "_source_file": "a.pdf"}]})
    _write(new / "Cairns.json", {"restaurants": [
        {"name": "Alpha", "hours": "9", "_source_file": "b.pdf", "_source_date": "x"},
        {"name": "Gamma", "hours": "new", "_source_file": "b.pdf"}]})
    _write(old / "Rome.json", {"attractions": [{"name": "Forum"}, {"name": "Colosseum", "_source_file": "z"}]})
    _write(new / "Rome.json", {"attractions": []})
    out = tmp_path / "c.md"
    write_edit_candidates(old, new, second, repo, out)
    text = out.read_text(encoding="utf-8")
    assert "Beta" in text and "Gamma" in text
    cairns = text.split("Old items without a provenance marker")[0]
    assert "Alpha" not in cairns
    assert "Colosseum" not in cairns  # Rome is not a candidate city
    tail = text.split("Old items without a provenance marker")[1]
    assert "Forum" in tail and "Colosseum" not in tail
    write_edit_candidates(old, new, second, repo, tmp_path / "c2.md")
    assert (tmp_path / "c2.md").read_text(encoding="utf-8") == text


def test_edit_candidates_caps_provenance_list(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _write(old / "Rome.json", {"attractions": [{"name": f"A{i:03d}"} for i in range(60)]})
    _write(new / "Rome.json", {"attractions": []})
    out = tmp_path / "c.md"
    write_edit_candidates(old, new, None, tmp_path, out)
    assert "... and 10 more" in out.read_text(encoding="utf-8")


def test_backup_library(tmp_path):
    repo, _, _ = _repo(tmp_path)
    lib = repo / "aig-library"
    _write(lib / "x" / "f.txt", {})
    dest = tmp_path / "bk"
    backup_library(repo / "library_db", lib, dest, "pre-rebuild")
    assert (dest / "library_db" / "Cairns.json").exists()
    assert (dest / "aig-library" / "x" / "f.txt").exists()
    assert "pre-rebuild" in _git(repo, "tag").split()
    with pytest.raises(ValueError, match="exists"):
        backup_library(repo / "library_db", lib, dest, "t2")
    with pytest.raises(ValueError, match="tag"):
        backup_library(repo / "library_db", lib, tmp_path / "bk2", "pre-rebuild")
    assert not (tmp_path / "bk2").exists()
    with pytest.raises(ValueError, match="missing"):
        backup_library(repo / "library_db", tmp_path / "nolib", tmp_path / "bk3", "t3")


def test_cli_backup_and_edit_candidates(tmp_path):
    repo, _, second = _repo(tmp_path)
    lib = repo / "aig-library"
    _write(lib / "f.json", {})
    res = runner.invoke(cli.app, ["backup", "--dest", str(tmp_path / "bk"), "--tag", "t1",
                                  "--db", str(repo / "library_db"), "--library", str(lib)])
    assert res.exit_code == 0, res.output
    assert "files" in res.output
    res = runner.invoke(cli.app, ["backup", "--dest", str(tmp_path / "bk"), "--tag", "t2",
                                  "--db", str(repo / "library_db"), "--library", str(lib)])
    assert res.exit_code == 1

    new = tmp_path / "new"
    _write(new / "Cairns.json", {"restaurants": []})
    out = tmp_path / "c.md"
    res = runner.invoke(cli.app, ["edit-candidates", "--old", str(repo / "library_db"), "--new", str(new),
                                  "--git-commit", second, "--out", str(out), "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    assert out.exists()


def test_rebuild_loads_blocklist(tmp_path, monkeypatch):
    from src.library.ingest_core import runner as runner_mod
    from src.library.ui.services.db_service import LibraryDBService
    from src.library.ui.storage import LocalStorageBackend
    from tests.library.test_plan_pilot import _Client, _write_plan

    repo, _, second = _repo(tmp_path)
    d = _write_plan(tmp_path, 1)
    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: _Client())
    monkeypatch.setattr(cli, "_repo_root", lambda: repo)
    seen = {}

    def fake(entries, db, client, **k):
        seen["bl"] = db.get_blocklist()
        from src.library.ingest_core.runner import IngestReport
        return IngestReport()

    monkeypatch.setattr(runner_mod, "run_ingest", fake)
    db = tmp_path / "new"
    res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(db), "--max-usd", "5",
                                  "--blocklist-from-git", second])
    assert res.exit_code == 0, res.output
    assert {"city": "Cairns", "list": "restaurants", "key": "beta"} in seen["bl"]
    assert "2 blocklist entries" in res.output
    assert LibraryDBService(LocalStorageBackend(db)).get_blocklist()


def test_non_ascii_shard_name(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for a in (("init", "-q"), ("config", "user.email", "t@e.com"), ("config", "user.name", "T"),
              ("config", "commit.gpgsign", "false")):
        _git(repo, *a)
    _write(repo / "library_db" / "Zürich.json", {"restaurants": [{"name": "Alpha"}, {"name": "Beta"}]})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a")
    _write(repo / "library_db" / "Zürich.json", {"restaurants": [{"name": "Alpha"}]})
    _git(repo, "commit", "-qam", "b")
    got = build_blocklist(tmp_path / "none.json", "HEAD", repo)
    assert got == [{"city": "Zürich", "list": "restaurants", "key": "beta"}]
    old, new = tmp_path / "old", tmp_path / "new"
    _write(old / "Zürich.json", {"restaurants": [{"name": "Beta", "_source_file": "x"}]})
    _write(new / "Zürich.json", {"restaurants": []})
    write_edit_candidates(old, new, "HEAD", repo, tmp_path / "c.md")
    assert "Beta" in (tmp_path / "c.md").read_text(encoding="utf-8").split("## Old items")[0]


def test_invalid_commit_refs(tmp_path, monkeypatch):
    repo, first, second = _repo(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        build_blocklist(tmp_path / "n.json", "deadbeefdeadbeef", repo)
    with pytest.raises(ValueError, match="not found"):
        write_edit_candidates(tmp_path, tmp_path, "deadbeefdeadbeef", repo, tmp_path / "o.md")
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    for bad in ("--output=/tmp/x", "-h", "a b", ""):
        with pytest.raises(ValueError, match="not a valid commit reference"):
            build_blocklist(tmp_path / "n.json", bad, repo)
    assert called == []
    monkeypatch.undo()
    assert build_blocklist(tmp_path / "n.json", second[:8], repo)


def test_rebuild_bad_sha_creates_nothing(tmp_path, monkeypatch):
    from src.library.ingest_core import runner as runner_mod
    from tests.library.test_plan_pilot import _Client, _write_plan

    repo, _, _ = _repo(tmp_path)
    d = _write_plan(tmp_path, 1)
    monkeypatch.setattr(cli, "_repo_root", lambda: repo)
    called = []
    monkeypatch.setattr("src.common.ai_provider.get_ai_client", lambda **k: called.append("client") or _Client())
    monkeypatch.setattr(runner_mod, "run_ingest", lambda *a, **k: called.append("run"))
    db = tmp_path / "new"
    for bad in ("deadbeefdeadbeef", "--output=/tmp/x"):
        res = runner.invoke(cli.app, ["rebuild", "--plan", str(d), "--db", str(db), "--max-usd", "5",
                                      "--blocklist-from-git", bad])
        assert res.exit_code == 1, res.output
        assert not db.exists()
    assert called == []


def test_backup_copy_failure_cleans_up(tmp_path, monkeypatch):
    import shutil
    repo, _, _ = _repo(tmp_path)
    lib = repo / "aig-library"
    _write(lib / "f.json", {})

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copytree", boom)
    dest = tmp_path / "bk"
    with pytest.raises(ValueError, match="disk full"):
        backup_library(repo / "library_db", lib, dest, "t1")
    assert not dest.exists()
    assert "t1" not in _git(repo, "tag").split()


def test_backup_tag_failure_keeps_copy(tmp_path, monkeypatch):
    from src.library.ingest_core import edits
    repo, _, _ = _repo(tmp_path)
    lib = repo / "aig-library"
    _write(lib / "f.json", {})
    real = edits._git

    def fake(r, *args):
        if args[:1] == ("tag",) and "--list" not in args:
            raise ValueError("nope")
        return real(r, *args)

    monkeypatch.setattr(edits, "_git", fake)
    dest = tmp_path / "bk"
    with pytest.raises(ValueError, match="complete backup was written to .*creating tag t1 failed: nope"):
        backup_library(repo / "library_db", lib, dest, "t1")
    assert (dest / "library_db").exists()


def test_cli_backup_warns_on_uncommitted(tmp_path):
    repo, _, _ = _repo(tmp_path)
    lib = repo / "aig-library"
    _write(lib / "f.json", {})
    _write(repo / "library_db" / "Cairns.json", {"restaurants": []})
    res = runner.invoke(cli.app, ["backup", "--dest", str(tmp_path / "bk"), "--tag", "t1",
                                  "--db", str(repo / "library_db"), "--library", str(lib)])
    assert res.exit_code == 0, res.output
    assert "does NOT include the uncommitted" in " ".join(res.output.split())


def test_edit_candidates_warns_without_audit(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _write(old / "Rome.json", {"attractions": []})
    _write(new / "Rome.json", {"attractions": []})
    res = runner.invoke(cli.app, ["edit-candidates", "--old", str(old), "--new", str(new),
                                  "--out", str(tmp_path / "c.md")])
    assert res.exit_code == 0, res.output
    assert "no audit log found" in res.output


@pytest.mark.parametrize("n,more", [(50, None), (51, "... and 1 more")])
def test_cap_boundary(tmp_path, n, more):
    old, new = tmp_path / "old", tmp_path / "new"
    _write(old / "Rome.json", {"attractions": [{"name": f"A{i:03d}"} for i in range(n)]})
    _write(new / "Rome.json", {"attractions": []})
    write_edit_candidates(old, new, None, tmp_path, tmp_path / "c.md")
    text = (tmp_path / "c.md").read_text(encoding="utf-8")
    if more:
        assert more in text
    else:
        assert "... and" not in text
