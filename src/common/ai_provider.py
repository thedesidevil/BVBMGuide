"""Unified AI provider supporting OpenAI-compatible endpoints.

This module provides a unified interface for AI completions that works with:
- OpenAI API directly
- OpenAI-compatible endpoints (like internal gateways)
- Any model accessible through the endpoint (GPT-4, Claude, etc.)
"""

import os
import re
from typing import Optional

from dotenv import load_dotenv

# Load .env file
load_dotenv()

# (prefix, input $/1M tokens, output $/1M tokens) — prefix-matched against model name
_MODEL_PRICING: list[tuple[str, float, float]] = [
    ("gpt-6.1-sol",      2.00, 10.00),
    ("gpt-6-luna",       0.10,  0.50),
    ("claude-fable-5",   10.00, 50.00),
    ("claude-mythos-5",  10.00, 50.00),
    ("claude-sonnet-5",   2.00, 10.00),
    # Haiku 5.5 prompts above 100K tokens cost $0.50/$2.50; cost_usd stays flat
    # and the pilot report flags any such prompt.
    ("claude-haiku-5",    0.10,  0.50),
    ("claude-opus-4",     5.00, 25.00),
    ("claude-sonnet-4",   3.00, 15.00),
    ("claude-haiku-4",    1.00,  5.00),
    ("o4-mini",           1.10,  4.40),
    ("gpt-4o-mini",       0.15,  0.60),
    ("gpt-4o",            2.50, 10.00),
]


def _lookup_pricing(model: str) -> Optional[tuple[float, float]]:
    m = model.lower()
    for prefix, in_price, out_price in _MODEL_PRICING:
        if m.startswith(prefix):
            return (in_price, out_price)
    return None


def _drops_temperature(model: str) -> bool:
    """5.x Claude models reject ``temperature``."""
    return bool(re.match(r"claude-[a-z]+-5", (model or "").lower()))


class AIClient:
    """AI client using OpenAI-compatible API.
    
    Works with any OpenAI-compatible endpoint, including internal gateways
    that route to different models (GPT-4, Claude, etc.)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
        max_retries: Optional[int] = None,
    ):
        """Initialize the AI client.
        
        Args:
            api_key: API key (defaults to AI_API_KEY or OPENAI_API_KEY env var)
            base_url: Base URL for the API (defaults to AI_BASE_URL or OPENAI_BASE_URL env var)
            model: Model name (defaults to AI_MODEL env var, or "gpt-4o")
            timeout: Per-request timeout in seconds
            max_retries: OpenAI client retry count (None keeps the library default)
        """
        from openai import OpenAI
        
        # Get configuration from environment with fallbacks
        self.api_key = api_key or os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        self.model = model or os.environ.get("AI_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o"
        
        if not self.api_key:
            raise ValueError(
                "No API key configured. Set one of:\n"
                "  - AI_API_KEY (preferred)\n"
                "  - OPENAI_API_KEY"
            )
        
        # Initialize OpenAI client (works with any OpenAI-compatible endpoint)
        client_kwargs: dict = {"api_key": self.api_key, "base_url": self.base_url, "timeout": timeout}
        if max_retries is not None:
            client_kwargs["max_retries"] = max_retries
        self._client = OpenAI(**client_kwargs)

        # Accumulated token counts across all complete_json() calls on this instance
        self.usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    
    def _create(self, *, temperature: Optional[float] = None, **kwargs):
        """One chat completion with the gateway-compat fallbacks.

        - 5.x Claude models never get ``temperature``.
        - An error mentioning ``temperature`` is retried once without it.
        - An error mentioning ``max_tokens`` is retried once with
          ``max_completion_tokens``. Any other error raises unchanged.
        Usage is added for every response that comes back.
        """
        if temperature is not None and not _drops_temperature(self.model):
            kwargs["temperature"] = temperature
        tried_temp = tried_tokens = False
        while True:
            try:
                response = self._client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                msg = str(e).lower()
                if "temperature" in msg and "temperature" in kwargs and not tried_temp:
                    tried_temp = True
                    kwargs.pop("temperature")
                elif "max_tokens" in msg and "max_tokens" in kwargs and not tried_tokens:
                    tried_tokens = True
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                else:
                    raise
        if response.usage:
            self.usage["prompt_tokens"]     += response.usage.prompt_tokens or 0
            self.usage["completion_tokens"] += response.usage.completion_tokens or 0
        return response

    def complete_with_images(
        self,
        prompt: str,
        images: list[str],
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> str:
        """Generate a completion from images + a text prompt (vision models).

        Args:
            prompt: Text instruction to accompany the images
            images: List of base64-encoded PNG strings (one per page)
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature
        """
        content: list[dict] = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        response = self._create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()

    def complete(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> str:
        """Generate a completion from the AI model.

        Args:
            prompt: The prompt to send to the model
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (0-1)
            system: Optional system prompt prepended before the user message

        Returns:
            The model's response text
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        return response.choices[0].message.content.strip()

    def complete_json_full(
        self,
        prompt: str,
        max_tokens: int = 8000,
        system: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """JSON-mode completion returning ``(text, finish_reason)``.

        Uses response_format=json_object and temperature=0 (dropped for models
        that reject it; see ``_create``). ``finish_reason`` is "length" when the
        output was cut off by ``max_tokens``.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            response_format={"type": "json_object"},
            messages=messages,
        )
        choice = response.choices[0]
        return (choice.message.content or "").strip(), getattr(choice, "finish_reason", None)

    def complete_json(
        self,
        prompt: str,
        max_tokens: int = 8000,
        system: Optional[str] = None,
    ) -> str:
        """Generate a JSON-mode completion; the text of ``complete_json_full``."""
        return self.complete_json_full(prompt, max_tokens=max_tokens, system=system)[0]

    @property
    def cost_usd(self) -> Optional[float]:
        """Estimated cost in USD based on accumulated usage. None if model pricing is unknown."""
        pricing = _lookup_pricing(self.model)
        if pricing is None:
            return None
        in_price, out_price = pricing
        return (
            self.usage["prompt_tokens"]     * in_price   / 1_000_000 +
            self.usage["completion_tokens"] * out_price  / 1_000_000
        )

    def __repr__(self):
        base = self.base_url or "https://api.openai.com/v1"
        # Truncate base URL for display
        if len(base) > 40:
            base = base[:37] + "..."
        return f"AIClient(model={self.model}, base_url={base})"


def get_ai_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,  # Kept for backward compatibility, ignored
    timeout: float = 300.0,
    max_retries: Optional[int] = None,
) -> AIClient:
    """Get an AI client with the specified configuration.
    
    Args:
        api_key: API key (or use AI_API_KEY/OPENAI_API_KEY env var)
        base_url: Base URL (or use AI_BASE_URL/OPENAI_BASE_URL env var)
        model: Model name (or use AI_MODEL/OPENAI_MODEL env var)
        provider: Deprecated, kept for compatibility
        
    Returns:
        Configured AIClient instance
    """
    return AIClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )

