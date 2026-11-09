import json

from src.library.qc import dump_contamination, dump_duplicates


def test_qc_dumps_skip_underscore_files(tmp_path):
    db = tmp_path / "db"
    db.mkdir()
    (db / "_index.json").write_text("{}")
    (db / "_place_overrides.json").write_text(json.dumps({"overrides": {"a|b": {"x": 1}}}))
    (db / "Rome.json").write_text(json.dumps({"restaurants": []}))
    assert dump_contamination(db, tmp_path / "c.tsv") == 0
    assert dump_duplicates(db, tmp_path / "d.tsv") == 0
