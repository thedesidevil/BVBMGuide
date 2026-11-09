import pytest

from src.aigv2.config import Settings


@pytest.mark.parametrize("bad", ["gpt-6-sol", "gpt-6.0-sol", "openai/gpt-6-sol", "azure:gpt-6.0-sol", "GPT-6-SOL"])
def test_banned_sol_rejected(bad):
    with pytest.raises(ValueError):
        Settings(models={"rank": bad})
    with pytest.raises(ValueError):
        Settings(models={}, fallback_model=bad)


@pytest.mark.parametrize("ok", ["gpt-6.1-sol", "openai/gpt-6.1-sol", "gpt-6-luna"])
def test_allowed_models(ok):
    Settings(models={"rank": ok})
