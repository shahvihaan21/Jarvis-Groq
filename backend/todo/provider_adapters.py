"""
AI Provider Adapters for Jarvis-Groq.

Supports Groq (default), OpenRouter, Ollama, and OpenAI-compatible inference endpoints
with explicit timeout handling, retries, and normalized application error classification.
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

from groq import Groq
from .config import GROQ_MODEL, GROQ_TIMEOUT_SECONDS
from .utils import retry_groq_call

logger = logging.getLogger(__name__)


class ProviderConfigurationError(Exception):
    """Raised when an AI provider configuration or API key is missing."""
    pass


class BaseAIProvider(ABC):
    """Abstract base class for all AI provider adapters."""

    @abstractmethod
    def stream_completion(
        self, messages: List[Dict[str, str]], model: str, request_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        """Yield structured SSE event dictionaries."""
        pass


# Singleton Groq client instance
_groq_client: Optional[Groq] = None


def get_groq_client(api_key: Optional[str] = None) -> Groq:
    """Return singleton Groq client with explicit timeout configured."""
    global _groq_client
    if _groq_client is None:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise ProviderConfigurationError("GROQ_API_KEY environment variable is missing.")
        _groq_client = Groq(api_key=key, timeout=GROQ_TIMEOUT_SECONDS)
    return _groq_client


class GroqProviderAdapter(BaseAIProvider):
    """Adapter for Groq cloud API endpoints."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = GROQ_TIMEOUT_SECONDS):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.timeout = timeout

    def get_client(self) -> Groq:
        return get_groq_client(self.api_key)

    def stream_completion(
        self, messages: List[Dict[str, str]], model: str, request_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        client = get_groq_client(self.api_key)
        active_model = model or GROQ_MODEL

        stream = retry_groq_call(
            lambda: client.chat.completions.create(
                model=active_model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=2048,
            )
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield {"type": "message_delta", "delta": delta}


class OpenAICompatibleAdapter(BaseAIProvider):
    """Adapter for OpenRouter, Ollama, and OpenAI-compatible completion endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = GROQ_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "dummy-key")
        self.timeout = timeout

    def stream_completion(
        self, messages: List[Dict[str, str]], model: str, request_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        import urllib.request
        import urllib.error

        active_model = model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-Request-ID": request_id,
        }

        payload = json.dumps({
            "model": active_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if decoded.startswith("data: "):
                        content = decoded[6:]
                        if content == "[DONE]":
                            break
                        try:
                            data = json.loads(content)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield {"type": "message_delta", "delta": delta}
                        except json.JSONDecodeError:
                            continue
        except Exception as err:
            logger.exception("openai_compatible_stream_error", extra={"request_id": request_id, "url": url})
            raise err


def get_provider_adapter(provider_name: Optional[str] = None) -> BaseAIProvider:
    """Return configured provider adapter instance."""
    provider = (provider_name or os.getenv("AI_PROVIDER", "groq")).lower()

    if provider == "groq":
        return GroqProviderAdapter()
    elif provider in ("openai", "openrouter", "ollama"):
        base_url = "http://localhost:11434/v1" if provider == "ollama" else None
        return OpenAICompatibleAdapter(base_url=base_url)

    # Fallback to Groq
    return GroqProviderAdapter()


def classify_provider_error(error: Exception) -> str:
    """
    Normalize failures into application error categories:
    - validation
    - authentication
    - rate_limit
    - timeout
    - provider_failure
    - streaming
    - internal
    """
    if isinstance(error, ProviderConfigurationError):
        return "provider_failure"

    status = getattr(error, "status_code", None)
    name = type(error).__name__.lower()
    err_str = str(error).lower()

    if status in (401, 403) or "unauthorized" in err_str or "forbidden" in err_str:
        return "authentication"
    if status == 429 or "rate" in name or "rate limit" in err_str:
        return "rate_limit"
    if "timeout" in name or "timed out" in err_str or "deadline_exceeded" in err_str:
        return "timeout"
    if status and 400 <= status < 500:
        return "validation"
    if status and status >= 500:
        return "provider_failure"

    return "provider_failure"
