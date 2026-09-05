"""
Jarvis AI — 100% stateless chat views and tool APIs.

The Django server is a thin, stateless proxy: the browser owns the
conversation history (JS array) and sends it with every request. Inference
is streamed from the Groq / Multi-provider API via SSE. Nothing is stored server-side.
"""

import hashlib
import json
import logging
import os
import datetime
import uuid

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from .config import GROQ_MODEL, MAX_HISTORY_TURNS, MAX_MESSAGE_CHARS, MAX_REQUEST_BYTES, SYSTEM_PROMPT
from .provider import stream_provider_completion, sanitize_log_extra
from .tools import execute_tool, get_registered_tools_schema, ToolExecutionError
from .utils import claim_request

logger = logging.getLogger(__name__)


def frontend_asset_version() -> str:
    """Return a content version so browsers fetch changed static assets."""
    static_dir = settings.BASE_DIR.parent / "frontend" / "static"
    digest = hashlib.sha256()
    for relative_path in ("css/style.css", "js/chat.js"):
        try:
            digest.update((static_dir / relative_path).read_bytes())
        except OSError:
            digest.update(relative_path.encode())
    return digest.hexdigest()[:16]


def index(request):
    active_model = GROQ_MODEL
    response = render(request, "todo/index.html", {
        "model_name": active_model,
        "frontend_version": frontend_asset_version(),
    })
    response["Cache-Control"] = "no-cache, must-revalidate"
    return response


def new_chat(request):
    return redirect("index")


def delete_chat(request, conversation_id=None):
    return redirect("index")


def test_frontend(request):
    return render(request, "todo/test_frontend.html")


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
@csrf_exempt
def chat_api(request):
    """
    Stateless SSE streaming endpoint.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    if len(request.body) > MAX_REQUEST_BYTES:
        return JsonResponse({"error": "Request payload is too large"}, status=413)

    try:
        data = json.loads(request.body) if request.body else {}
        if not isinstance(data, dict):
            return JsonResponse({"error": "JSON object expected"}, status=400)

        raw_prompt = data.get("message")
        if not isinstance(raw_prompt, str):
            return JsonResponse({"error": "Message content must be a string"}, status=400)
        prompt = raw_prompt.strip()
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

        # Sanitise history payload
        history = []
        for msg in raw_history[-MAX_HISTORY_TURNS:]:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            raw_content = msg.get("content")
            if not isinstance(raw_content, str):
                continue
            content = raw_content.strip()
            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})

        messages_payload = [{
            "role": "system",
            "content": SYSTEM_PROMPT,
        }] + history + [{"role": "user", "content": prompt[:MAX_MESSAGE_CHARS]}]

        response = StreamingHttpResponse(
            stream_provider_completion(messages_payload, request_id),
            content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["X-Request-ID"] = request_id
        return response

    except Exception:
        logger.exception("chat_api_error")
        return JsonResponse({"error": "Unable to process this request.", "category": "server_error"}, status=500)


@csrf_exempt
def tools_api(request):
    """
    Tools endpoint: GET returns tool schemas, POST executes a registered tool.
    """
    if request.method == "GET":
        return JsonResponse({"tools": get_registered_tools_schema()})
    elif request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
            tool_name = data.get("tool")
            arguments = data.get("arguments", {})
            request_id = str(data.get("request_id") or uuid.uuid4())

            if not tool_name:
                return JsonResponse({"error": "tool parameter is required"}, status=400)

            res = execute_tool(tool_name, arguments, request_id)
            return JsonResponse(res)
        except ToolExecutionError as te:
            return JsonResponse({"error": str(te), "category": "tool_error"}, status=400)
        except Exception as e:
            logger.exception("tools_api_error")
            return JsonResponse({"error": "Tool execution failed", "category": "internal"}, status=500)
    return JsonResponse({"error": "Method not allowed"}, status=405)


def health(request):
    """
    Safe health / readiness check endpoint.
    Deliberately contains no secret keys or sensitive configuration details.
    """
    provider_name = os.getenv("AI_PROVIDER", "groq").lower()
    has_groq_key = bool(os.getenv("GROQ_API_KEY"))

    return JsonResponse({
        "status": "ok",
        "service": "jarvis-groq",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider": provider_name,
        "provider_configured": has_groq_key if provider_name == "groq" else True,
    })
