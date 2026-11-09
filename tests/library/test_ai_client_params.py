import pytest

from src.common.ai_provider import AIClient, get_ai_client


class _Obj:
    pass


class _Resp:
    def __init__(self, text="{}", finish="stop", usage=(3, 2)):
        m = _Obj()
        m.content = text
        c = _Obj()
        c.message = m
        c.finish_reason = finish
        self.choices = [c]
        u = _Obj()
        u.prompt_tokens, u.completion_tokens = usage
        self.usage = u


class _Completions:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(script, model="gpt-4o"):
    c = AIClient(api_key="k", base_url="http://localhost:1", model=model)
    comp = _Completions(script)
    chat = _Obj()
    chat.completions = comp
    o = _Obj()
    o.chat = chat
    c._client = o
    return c, comp


def test_claude_5x_never_sends_temperature():
    for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5"):
        c, comp = _client([_Resp(), _Resp()], model=model)
        c.complete("hi")
        c.complete_json("hi")
        assert all("temperature" not in call for call in comp.calls), model


def test_other_models_send_temperature():
    c, comp = _client([_Resp(), _Resp()], model="claude-opus-4-8")
    c.complete("hi")
    c.complete_json("hi")
    assert all("temperature" in call for call in comp.calls)


@pytest.mark.parametrize("method", ["complete", "complete_json", "complete_json_full"])
def test_temperature_error_retries_once_without(method):
    c, comp = _client([RuntimeError("Unsupported value: 'temperature' does not support 0"), _Resp()])
    getattr(c, method)("hi")
    assert len(comp.calls) == 2 and "temperature" in comp.calls[0] and "temperature" not in comp.calls[1]


def test_complete_with_images_temperature_fallback():
    c, comp = _client([RuntimeError("temperature is not allowed"), _Resp()])
    c.complete_with_images("hi", ["abc"])
    assert "temperature" not in comp.calls[1]


@pytest.mark.parametrize("method", ["complete", "complete_json", "complete_with_images"])
def test_max_tokens_error_retries_with_max_completion_tokens(method):
    c, comp = _client([RuntimeError("Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'"), _Resp()])
    if method == "complete_with_images":
        c.complete_with_images("hi", ["abc"])
    else:
        getattr(c, method)("hi")
    assert "max_tokens" in comp.calls[0] and "max_tokens" not in comp.calls[1]
    assert comp.calls[1]["max_completion_tokens"] == comp.calls[0]["max_tokens"]


def test_both_fallbacks_chain_each_once():
    c, comp = _client([RuntimeError("bad temperature"), RuntimeError("bad max_tokens"), _Resp()])
    c.complete("hi")
    assert len(comp.calls) == 3
    assert "temperature" not in comp.calls[2] and "max_completion_tokens" in comp.calls[2]


@pytest.mark.parametrize("method", ["complete", "complete_json", "complete_json_full"])
def test_other_errors_still_raise_without_retry(method):
    c, comp = _client([RuntimeError("rate limited"), _Resp()])
    with pytest.raises(RuntimeError, match="rate limited"):
        getattr(c, method)("hi")
    assert len(comp.calls) == 1


def test_repeated_temperature_error_raises_after_one_retry():
    c, comp = _client([RuntimeError("temperature"), RuntimeError("temperature again")])
    with pytest.raises(RuntimeError):
        c.complete("hi")
    assert len(comp.calls) == 2


def test_complete_json_full_returns_finish_reason_and_counts_usage():
    c, _ = _client([_Resp('{"a": 1}', finish="length", usage=(10, 4))])
    assert c.complete_json_full("hi") == ('{"a": 1}', "length")
    assert c.usage == {"prompt_tokens": 10, "completion_tokens": 4}


def test_complete_json_is_wrapper():
    c, _ = _client([_Resp('{"a": 1}')])
    assert c.complete_json("hi") == '{"a": 1}'


def test_usage_kept_across_retry():
    c, _ = _client([RuntimeError("temperature"), _Resp(usage=(5, 5))])
    c.complete_json("hi")
    assert c.usage == {"prompt_tokens": 5, "completion_tokens": 5}


def test_timeout_and_retries_passed_to_openai(monkeypatch):
    seen = {}

    class FakeOpenAI:
        def __init__(self, **kw):
            seen.update(kw)

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    AIClient(api_key="k", model="m")
    assert seen["timeout"] == 300.0 and "max_retries" not in seen
    seen.clear()
    get_ai_client(api_key="k", model="m", timeout=600.0, max_retries=1)
    assert seen["timeout"] == 600.0 and seen["max_retries"] == 1


def test_get_ingest_client_uses_long_timeout_and_one_retry(monkeypatch):
    from src.library.ingest_core.extract import get_ingest_client
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return "client"

    monkeypatch.setattr("src.common.ai_provider.get_ai_client", fake)
    assert get_ingest_client("m1") == "client"
    assert seen["timeout"] == 600.0 and seen["max_retries"] == 1 and seen["model"] == "m1"
