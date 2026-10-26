from src.common.ai_provider import _lookup_pricing


def test_claude_5x_pricing():
    assert _lookup_pricing("claude-sonnet-5-5") == (2.00, 10.00)
    assert _lookup_pricing("claude-haiku-5-5") == (0.10, 0.50)


def test_claude_4x_pricing_not_shadowed():
    assert _lookup_pricing("claude-sonnet-4-6") == (3.00, 15.00)
    assert _lookup_pricing("claude-haiku-4-5") == (1.00, 5.00)
