"""
Clean provider/service layer isolating AI inference from Django views.

Routes through provider_adapters for multi-provider support (Groq, OpenRouter, Ollama).
Handles structured privacy-safe logging and standardized SSE completion streaming.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional

from .config import GROQ_MODEL, GROQ_TIMEOUT_SECONDS, SYSTEM_PROMPT
from .provider_adapters import (
    ProviderConfigurationError,
    classify_provider_error,
    get_groq_client,
    get_provider_adapter,
)
from .utils import retry_groq_call

logger = logging.getLogger(__name__)


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
    messages_payload: List[Dict[str, str]], request_id: str, model: Optional[str] = None
) -> Generator[str, None, None]:
    """
    Generate Server-Sent Events using standardized event protocol:
    - message_start    -> data: {"type": "message_start", ...}
    - message_delta    -> data: {"type": "message_delta", "delta": "..."}
    - message_complete -> data: {"type": "message_complete", "duration_ms": 123, "token_count": 45}
    - message_error    -> data: {"type": "message_error", "category": "...", "error": "..."}
    """
    active_model = model or GROQ_MODEL
    active_provider_name = os.getenv("AI_PROVIDER", "groq").lower()

    # Emit message_start event
    yield f"data: {json.dumps({'type': 'message_start', 'request_id': request_id, 'model': active_model, 'provider': active_provider_name, 'timestamp': int(time.time() * 1000)})}\n\n"

    try:
        adapter = get_provider_adapter(active_provider_name)
        started = time.perf_counter()
        output_chars = 0

        for event in adapter.stream_completion(messages_payload, active_model, request_id):
            if event.get("type") == "message_delta":
                delta = event.get("delta", "")
                if delta:
                    output_chars += len(delta)
                    yield f"data: {json.dumps({'type': 'message_delta', 'delta': delta})}\n\n"

        duration_ms = round((time.perf_counter() - started) * 1000)
        token_count = max(0, round(output_chars / 4))

        logger.info(
            "ai_chat_complete",
            extra=sanitize_log_extra({
                "request_id": request_id,
                "provider": active_provider_name,
                "model": active_model,
                "duration_ms": duration_ms,
                "token_count": token_count,
            }),
        )

        yield f"data: {json.dumps({'type': 'message_complete', 'request_id': request_id, 'duration_ms': duration_ms, 'token_count': token_count})}\n\n"

    except Exception as stream_err:
        category = classify_provider_error(stream_err)
        logger.exception(
            "ai_stream_error",
            extra=sanitize_log_extra({
                "request_id": request_id,
                "provider": active_provider_name,
                "model": active_model,
                "error_category": category,
            }),
        )
        user_msg = (
            "The request timed out while contacting the AI service."
            if category == "timeout"
            else "The AI service rate limit was reached. Please try again shortly."
            if category == "rate_limit"
            else "Authentication with AI provider failed. Check credentials."
            if category == "authentication"
            else "The AI service is temporarily unavailable."
        )
        yield f"data: {json.dumps({'type': 'message_error', 'request_id': request_id, 'category': category, 'error': user_msg})}\n\n"
