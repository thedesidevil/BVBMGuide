"""Unified AI provider supporting OpenAI-compatible endpoints.

This module provides a unified interface for AI completions that works with:
- OpenAI API directly
- OpenAI-compatible endpoints (like internal gateways)
- Any model accessible through the endpoint (GPT-4, Claude, etc.)
"""

import os
from typing import Optional

from dotenv import load_dotenv

# Load .env file
load_dotenv()


class AIClient:
    """AI client using OpenAI-compatible API.
    
    Works with any OpenAI-compatible endpoint, including internal gateways
    that route to different models (GPT-4, Claude, etc.)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        """Initialize the AI client.
        
        Args:
            api_key: API key (defaults to AI_API_KEY or OPENAI_API_KEY env var)
            base_url: Base URL for the API (defaults to AI_BASE_URL or OPENAI_BASE_URL env var)
            model: Model name (defaults to AI_MODEL env var, or "gpt-4o")
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
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=300.0,
        )
    
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
        response = self._client.chat.completions.create(
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
        temperature: float = 0.7
    ) -> str:
        """Generate a completion from the AI model.
        
        Args:
            prompt: The prompt to send to the model
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (0-1)
            
        Returns:
            The model's response text
        """
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    
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
    provider: Optional[str] = None  # Kept for backward compatibility, ignored
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
        model=model
    )

