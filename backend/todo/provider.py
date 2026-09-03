"""
Clean provider/service layer isolating Groq AI inference logic from Django views.

Handles client configuration, error classification, explicit upstream timeouts,
structured privacy-safe logging, and SSE completion streaming.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Generator, List

from groq import Groq
from .config import GROQ_MODEL, GROQ_TIMEOUT_SECONDS, SYSTEM_PROMPT
from .utils import retry_groq_call

logger = logging.getLogger(__name__)

_client = None


class ProviderConfigurationError(Exception):
    """Raised when the AI provider API key or environment is missing."""
    pass


def get_groq_client() -> Groq:
    """Return singleton Groq client with explicit timeout configured."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ProviderConfigurationError("AI provider is not configured")
        _client = Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS)
    return _client


def classify_provider_error(error: Exception) -> str:
    """
    Classify failures into standard user-safe categories:
    - timeout
    - rate_limit
    - invalid_request
    - provider_failure
    - server_error
    """
    if isinstance(error, ProviderConfigurationError):
        return "provider_failure"

    status = getattr(error, "status_code", None)
    name = type(error).__name__.lower()
    err_str = str(error).lower()

    if status == 429 or "rate" in name or "rate limit" in err_str:
        return "rate_limit"
    if "timeout" in name or "timed out" in err_str or "timeout" in err_str or "deadline_exceeded" in err_str:
        return "timeout"
    if status and 400 <= status < 500:
        return "invalid_request"
    if status and status >= 500:
        return "provider_failure"

    return "provider_failure"



def sanitize_log_extra(extra_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure no raw prompts, tokens, or API keys are logged."""
    safe = {}
    sensitive_keys = {"api_key", "key", "token", "password", "authorization", "secret", "prompt", "message", "content"}
    for k, v in extra_dict.items():
        if k.lower() in sensitive_keys:
            continue
        safe[k] = v
    return safe


def stream_provider_completion(
    messages_payload: List[Dict[str, str]], request_id: str
) -> Generator[str, None, None]:
    """
    Generate Server-Sent Events for streaming completion.

    SSE formats:
    - init  -> data: {"type": "init", "model": "...", "request_id": "..."}
    - chunk -> data: {"type": "chunk", "delta": "..."}
    - done  -> data: {"type": "done", "duration_ms": 123, "token_count": 45}
    - error -> data: {"type": "error", "category": "...", "error": "..."}
    """
    active_model = GROQ_MODEL
    yield f"data: {json.dumps({'type': 'init', 'model': active_model, 'request_id': request_id})}\n\n"

    try:
        client = get_groq_client()
        started = time.perf_counter()
        output_chars = 0

        stream = retry_groq_call(
            lambda: client.chat.completions.create(
                model=active_model,
                messages=messages_payload,
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
                output_chars += len(delta)
                yield f"data: {json.dumps({'type': 'chunk', 'delta': delta})}\n\n"

        duration_ms = round((time.perf_counter() - started) * 1000)
        token_count = max(0, round(output_chars / 4))

        logger.info(
            "groq_chat_complete",
            extra=sanitize_log_extra({
                "request_id": request_id,
                "model": active_model,
                "duration_ms": duration_ms,
                "token_count": token_count,
            }),
        )
        yield f"data: {json.dumps({'type': 'done', 'duration_ms': duration_ms, 'token_count': token_count})}\n\n"

    except Exception as stream_err:
        category = classify_provider_error(stream_err)
        logger.exception(
            "groq_stream_error",
            extra=sanitize_log_extra({
                "request_id": request_id,
                "model": active_model,
                "error_category": category,
            }),
        )
        user_msg = (
            "The request timed out while contacting the AI service."
            if category == "timeout"
            else "The AI service rate limit was reached. Please try again shortly."
            if category == "rate_limit"
            else "The AI service is temporarily unavailable."
        )
        yield f"data: {json.dumps({'type': 'error', 'category': category, 'error': user_msg})}\n\n"
