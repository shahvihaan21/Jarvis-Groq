"""
Jarvis AI — 100% stateless chat views.

The Django server is a thin, stateless proxy: the browser owns the
conversation history (JS array) and sends it with every request. Inference
is streamed from the Groq API via SSE. Nothing is stored server-side.
"""

import json
import logging
import os
import time
import uuid
from typing import Generator

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from groq import Groq
from .utils import claim_request, retry_groq_call

logger = logging.getLogger(__name__)

# Default Groq production model (override via GROQ_MODEL env var)
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_HISTORY_TURNS = 12    # Bound context turns
MAX_MESSAGE_CHARS = 8000  # Input guard per message
MAX_REQUEST_BYTES = 256 * 1024

_client = None


def get_groq_client() -> Groq:
    """Lazily create and reuse a single Groq client per worker process."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not configured. "
                "Please add GROQ_API_KEY in your Vercel/Render/Railway environment settings."
            )
        _client = Groq(api_key=api_key, timeout=45.0)
    return _client


def index(request):
    active_model = os.getenv("GROQ_MODEL", GROQ_MODEL)
    response = render(request, "todo/index.html", {"model_name": active_model})
    # The HTML shell references mutable CSS/JS files. Revalidate it on every
    # request so frontend updates are not hidden behind a one-hour cache.
    response["Cache-Control"] = "no-cache, must-revalidate"
    return response


def new_chat(request):
    return redirect("index")


def delete_chat(request, conversation_id=None):
    # Stateless: conversations live only in client browser memory
    return redirect("index")


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
@csrf_exempt
def chat_api(request):
    """
    Stateless SSE streaming endpoint.

    Expects JSON:
        {
          "message": "the new user prompt",
          "history": [{"role": "user"|"assistant", "content": "..."}, ...]
        }

    Streams Server-Sent Events back:
        init  -> metadata (model name)
        chunk -> one token delta
        done  -> stream finished
        error -> error message
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    if len(request.body) > MAX_REQUEST_BYTES:
        return JsonResponse({"error": "Request payload is too large"}, status=413)

    try:
        data = json.loads(request.body) if request.body else {}
        if not isinstance(data, dict):
            return JsonResponse({"error": "JSON object expected"}, status=400)
        prompt = (data.get("message") or "").strip()
        raw_history = data.get("history", [])
        request_id = str(data.get("request_id") or "")

        if not request_id or len(request_id) > 80:
            return JsonResponse({"error": "A valid request_id is required"}, status=400)
        try:
            uuid.UUID(request_id)
        except ValueError:
            return JsonResponse({"error": "request_id must be a UUID"}, status=400)
        if not isinstance(raw_history, list):
            return JsonResponse({"error": "history must be a list"}, status=400)

        if not prompt:
            return JsonResponse({"error": "Message content is required"}, status=400)
        if len(prompt) > MAX_MESSAGE_CHARS:
            return JsonResponse({"error": f"Message exceeds {MAX_MESSAGE_CHARS} characters"}, status=400)
        if not claim_request(request_id):
            return JsonResponse({"error": "Duplicate request_id"}, status=409)

        # Sanitise client-supplied history (whitelist roles & enforce length limits)
        history = []
        for msg in raw_history[-MAX_HISTORY_TURNS:]:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})

        messages_payload = [{
            "role": "system",
            "content": (
                "You are Jarvis AI, a highly intelligent, fast, and helpful AI assistant. "
                "Answer clearly and accurately. Use Markdown for formatting and code blocks."
            ),
        }] + history + [{"role": "user", "content": prompt[:MAX_MESSAGE_CHARS]}]

        active_model = os.getenv("GROQ_MODEL", GROQ_MODEL)

        def stream_generator() -> Generator[str, None, None]:
            yield f"data: {json.dumps({'type': 'init', 'model': active_model})}\n\n"
            try:
                client = get_groq_client()
                started = time.perf_counter()
                output_chars = 0
                stream = retry_groq_call(lambda: client.chat.completions.create(
                    model=active_model, messages=messages_payload, stream=True,
                    temperature=0.7, max_tokens=2048,
                ))
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        output_chars += len(delta)
                        yield f"data: {json.dumps({'type': 'chunk', 'delta': delta})}\n\n"
                duration_ms = round((time.perf_counter() - started) * 1000)
                token_count = max(0, round(output_chars / 4))
                logger.info("groq_chat_complete", extra={"model": active_model, "duration_ms": duration_ms, "token_count": token_count})
                yield f"data: {json.dumps({'type': 'done', 'duration_ms': duration_ms, 'token_count': token_count})}\n\n"
            except Exception as stream_err:
                logger.exception("groq_stream_error", extra={"model": active_model})
                yield f"data: {json.dumps({'type': 'error', 'error': 'The AI service is temporarily unavailable.'})}\n\n"

        response = StreamingHttpResponse(stream_generator(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        return response

    except Exception as e:
        logger.exception("chat_api_error")
        return JsonResponse({"error": str(e)}, status=500)
