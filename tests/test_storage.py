import json
from pathlib import Path

import pytest

from src.library.ui.storage import LocalStorageBackend


class TestLocalStorageBackend:
    def test_read_json_existing(self, tmp_path):
        (tmp_path / "test.json").write_text(json.dumps({"key": "value"}))
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_json("test.json") == {"key": "value"}

    def test_read_json_missing(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_json("missing.json") is None

    def test_write_json(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_json("out.json", {"hello": "world"})
        assert json.loads((tmp_path / "out.json").read_text()) == {"hello": "world"}

    def test_write_json_nested(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_json("sub/dir/out.json", {"nested": True})
        assert (tmp_path / "sub" / "dir" / "out.json").exists()

    def test_read_bytes(self, tmp_path):
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_bytes("binary.bin") == b"\x00\x01\x02"

    def test_read_bytes_missing(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        assert backend.read_bytes("nope.bin") is None

    def test_write_bytes(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.write_bytes("data.bin", b"hello")
        assert (tmp_path / "data.bin").read_bytes() == b"hello"

    def test_delete(self, tmp_path):
        (tmp_path / "doomed.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        backend.delete("doomed.json")
        assert not (tmp_path / "doomed.json").exists()

    def test_delete_missing_no_error(self, tmp_path):
        backend = LocalStorageBackend(tmp_path)
        backend.delete("nonexistent.json")  # should not raise

    def test_list_keys(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        keys = sorted(backend.list_keys(""))
        assert keys == ["a.json", "b.json", "sub/c.json"]

    def test_list_keys_with_prefix(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "one.json").write_text("{}")
        (tmp_path / "sub" / "two.json").write_text("{}")
        (tmp_path / "other.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        keys = sorted(backend.list_keys("sub/"))
        assert keys == ["sub/one.json", "sub/two.json"]

    def test_exists(self, tmp_path):
        (tmp_path / "yes.json").write_text("{}")
        backend = LocalStorageBackend(tmp_path)
        assert backend.exists("yes.json") is True
        assert backend.exists("no.json") is False
