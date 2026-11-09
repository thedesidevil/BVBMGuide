from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.aigv2.config import Settings
from src.aigv2.llm import LLMStepError, StepLLM


class Out(BaseModel):
    x: int


class FakeClient:
    def __init__(self, model, replies, calls, prompt_tokens=10):
        self.model = model
        self._replies = replies
        self._calls = calls
        self._prompt_tokens = prompt_tokens
        self._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    def _create(self, **kw):
        self._calls.append((self.model, kw))
        usage = SimpleNamespace(prompt_tokens=self._prompt_tokens, completion_tokens=0)
        msg = SimpleNamespace(content=self._replies[self.model])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def make(replies, prompt_tokens=10):
    calls = []
    settings = Settings(models={"rank": "gpt-6-luna"})
    llm = StepLLM(settings, client_factory=lambda m: FakeClient(m, replies, calls, prompt_tokens))
    return llm, calls


def test_valid_luna_output_no_fallback():
    llm, calls = make({"gpt-6-luna": '{"x": 1}'})
    assert llm.run_json("rank", "sys", "p", Out).x == 1
    assert len(llm.cost_log) == 1
    assert llm.cost_log[0]["fallback"] is False
    assert llm.cost_log[0]["model"] == "gpt-6-luna"
    kw = calls[0][1]
    assert kw["max_completion_tokens"] == 8000 and "max_tokens" not in kw
    assert kw["response_format"] == {"type": "json_object"}


def test_invalid_json_falls_back_to_sol():
    llm, _ = make({"gpt-6-luna": "not json", "gpt-6.1-sol": '{"x": 2}'})
    assert llm.run_json("rank", "sys", "p", Out).x == 2
    assert len(llm.cost_log) == 2
    assert llm.cost_log[1]["model"] == "gpt-6.1-sol"
    assert llm.cost_log[1]["fallback"] is True


def test_validator_problems_trigger_fallback():
    llm, calls = make({"gpt-6-luna": '{"x": 9}', "gpt-6.1-sol": '{"x": 1}'})
    validate = lambda o: ["day 9 outside trip dates"] if o.x == 9 else []
    assert llm.run_json("rank", "sys", "p", Out, validate=validate).x == 1
    sol_prompt = calls[1][1]["messages"][-1]["content"]
    assert "day 9 outside trip dates" in sol_prompt


def test_double_failure_raises():
    llm, _ = make({"gpt-6-luna": "bad", "gpt-6.1-sol": "worse"})
    with pytest.raises(LLMStepError) as e:
        llm.run_json("rank", "sys", "p", Out)
    assert e.value.step == "rank"
    assert len(llm.cost_log) == 2


def test_cost_uses_pricing():
    llm, _ = make({"gpt-6-luna": '{"x": 1}'}, prompt_tokens=1_000_000)
    llm.run_json("rank", "sys", "p", Out)
    assert llm.cost_log[0]["usd"] == pytest.approx(0.10)
    assert llm.total_usd() == pytest.approx(0.10)


def test_unpriced_model_is_flagged(caplog):
    calls = []
    settings = Settings(models={"rank": "mystery-model"})
    llm = StepLLM(settings, client_factory=lambda m: FakeClient(m, {"mystery-model": '{"x": 1}'}, calls))
    with caplog.at_level("WARNING"):
        llm.run_json("rank", "sys", "p", Out)
    assert llm.cost_log[0]["usd"] == 0.0 and llm.cost_log[0]["unpriced"] is True
    assert "mystery-model" in caplog.text and "no price" in caplog.text
