import json
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, override_settings
from todo.config import MAX_MESSAGE_CHARS
from todo.provider import ProviderConfigurationError


def setup_function():
    cache.clear()


def payload(**kwargs):
    value = {"message": "Hello", "history": [], "request_id": str(uuid.uuid4())}
    value.update(kwargs)
    return value


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_requires_message():
    response = Client().post("/api/chat/", data=json.dumps(payload(message="")), content_type="application/json")
    assert response.status_code == 400
    assert "Message content is required" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_validates_history():
    response = Client().post("/api/chat/", data=json.dumps(payload(history={})), content_type="application/json")
    assert response.status_code == 400
    assert "history must be a list" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_ignores_malformed_history_entries():
    response = Client().post(
        "/api/chat/",
        data=json.dumps(payload(history=[None, {"role": "user", "content": 123}])),
        content_type="application/json",
    )
    assert response.status_code == 200


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_validates_message_type():
    response = Client().post("/api/chat/", data=json.dumps(payload(message=123)), content_type="application/json")
    assert response.status_code == 400
    assert "Message content must be a string" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_requires_valid_request_id():
    response = Client().post("/api/chat/", data=json.dumps(payload(request_id="invalid-uuid")), content_type="application/json")
    assert response.status_code == 400
    assert "request_id must be a UUID" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_rejects_missing_request_id():
    response = Client().post("/api/chat/", data=json.dumps(payload(request_id="")), content_type="application/json")
    assert response.status_code == 400
    assert "request_id is required" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_rejects_oversized_payload():
    large_history = [{"role": "user", "content": "x" * 10000} for _ in range(30)]
    response = Client().post("/api/chat/", data=json.dumps(payload(history=large_history)), content_type="application/json")
    assert response.status_code == 413
    assert "payload is too large" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_rejects_oversized_prompt():
    huge_prompt = "a" * (MAX_MESSAGE_CHARS + 10)
    response = Client().post("/api/chat/", data=json.dumps(payload(message=huge_prompt)), content_type="application/json")
    assert response.status_code == 400
    assert "exceeds" in response.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
def test_chat_api_rejects_duplicate_request_id():
    req_id = str(uuid.uuid4())
    p = payload(request_id=req_id)
    r1 = Client().post("/api/chat/", data=json.dumps(p), content_type="application/json")
    assert r1.status_code == 200
    r2 = Client().post("/api/chat/", data=json.dumps(p), content_type="application/json")
    assert r2.status_code == 409
    assert "Duplicate request_id" in r2.json()["error"]


@override_settings(RATELIMIT_ENABLE=False)
@patch("todo.provider_adapters.get_groq_client")
def test_chat_api_streams_completion(mock_client):
    class Delta:
        content = "Hi"

    class Choice:
        delta = Delta()

    mock_client.return_value.chat.completions.create.return_value = [type("Chunk", (), {"choices": [Choice()]})()]
    response = Client().post("/api/chat/", data=json.dumps(payload()), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") is not None
    assert '"type": "message_complete"' in body


@override_settings(RATELIMIT_ENABLE=False)
@patch("todo.provider_adapters.retry_groq_call")
def test_chat_api_handles_streaming_provider_error(mock_retry):
    mock_retry.side_effect = TimeoutError("Groq connection timed out")
    response = Client().post("/api/chat/", data=json.dumps(payload()), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert response.status_code == 200
    assert '"type": "message_error"' in body
    assert '"category": "timeout"' in body



def test_health_endpoint_safety():
    response = Client().get("/api/health/")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert "GROQ_API_KEY" not in data
    assert "api_key" not in data
    assert "secret" not in data
