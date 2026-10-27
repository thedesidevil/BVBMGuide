"""Folder classifier: robust reply parsing, 512 tokens, prompt rules."""

import pytest

from src.library import ingester as ingester_mod
from src.library.ingester import LibraryIngester


class Stub:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, prompt, **kw):
        self.calls.append((prompt, kw))
        return self.reply


def _ing(tmp_path, monkeypatch, reply):
    monkeypatch.setattr(LibraryIngester, "_extract_preview", lambda self, p, max_chars=3000: "text")
    ing = LibraryIngester(tmp_path, api_key="k")
    ing.client = Stub(reply)
    return ing


@pytest.mark.parametrize("reply", [
    'The guide opens in Zurich, so Switzerland fits.\n\n{"folder": "Switzerland"}',
    '```json\n{"folder": "Switzerland"}\n```',
    '{"folder": "Switzerland"}',
    'Maybe {"note": 1} first.\n{"folder": "Switzerland"}\n',
    'Reasoning with {"folder": "Europe"} then final:\n{"folder": "Switzerland"}',
])
def test_replies_parse(tmp_path, monkeypatch, reply):
    ing = _ing(tmp_path, monkeypatch, reply)
    assert ing._classify_file_checked(tmp_path / "x.pdf", ["Italy"]) == ("Switzerland", None)


def test_no_json_is_an_error_and_classify_file_returns_none(tmp_path, monkeypatch):
    ing = _ing(tmp_path, monkeypatch, "I think it is Switzerland but I cannot say for sure.")
    folder, error = ing._classify_file_checked(tmp_path / "x.pdf", ["Italy"])
    assert folder is None
    assert error == ("ValueError: no folder JSON in reply: "
                     "I think it is Switzerland but I cannot say for sure.")
    assert ing._classify_file(tmp_path / "x.pdf", ["Italy"]) is None


def test_empty_folder_is_not_an_error(tmp_path, monkeypatch):
    ing = _ing(tmp_path, monkeypatch, '{"folder": ""}')
    assert ing._classify_file_checked(tmp_path / "x.pdf", []) == (None, None)


def test_max_tokens_and_prompt_rules(tmp_path, monkeypatch):
    ing = _ing(tmp_path, monkeypatch, '{"folder": "Italy"}')
    ing._classify_file_checked(tmp_path / "x.pdf", ["Italy", "Europe"])
    [(prompt, kw)] = ing.client.calls
    assert kw["max_tokens"] == 512 and kw["temperature"] == 0
    assert "NEVER pick a continent or region folder" in prompt
    assert "FIRST country named" in prompt
    assert "Reply with ONLY the JSON object" in prompt
    assert '{"folder": "<folder name>"}' in prompt
    assert "  - Italy" in prompt and "x.pdf" in prompt
