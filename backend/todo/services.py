"""
Provider boundary compatibility layer.

Delegates AI client management and error classification to provider.py.
"""

from .provider import (
    ProviderConfigurationError,
    classify_provider_error,
    get_groq_client,
    stream_provider_completion,
)

__all__ = [
    "ProviderConfigurationError",
    "classify_provider_error",
    "get_groq_client",
    "stream_provider_completion",
]
