"""
Provider boundary compatibility layer.

Delegates AI client management, multi-provider adapters, and error classification to provider.py and provider_adapters.py.
"""

from .provider import (
    ProviderConfigurationError,
    classify_provider_error,
    stream_provider_completion,
)
from .provider_adapters import GroqProviderAdapter, get_provider_adapter


def get_groq_client():
    """Return singleton Groq client instance."""
    adapter = GroqProviderAdapter()
    return adapter.get_client()


__all__ = [
    "ProviderConfigurationError",
    "classify_provider_error",
    "get_groq_client",
    "get_provider_adapter",
    "stream_provider_completion",
]
