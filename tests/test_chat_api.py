import json
import uuid
from unittest.mock import patch

from django.test import Client


def payload(**kwargs):
    value = {"message": "Hello", "history": [], "request_id": str(uuid.uuid4())}
    value.update(kwargs)
    return value


def test_chat_api_requires_message():
    response = Client().post("/api/chat/", data=json.dumps(payload(message="")), content_type="application/json")
    assert response.status_code == 400


def test_chat_api_validates_history():
    response = Client().post("/api/chat/", data=json.dumps(payload(history={})), content_type="application/json")
    assert response.status_code == 400


@patch("todo.views.get_groq_client")
def test_chat_api_streams_completion(mock_client):
    class Delta:
        content = "Hi"
    class Choice:
        delta = Delta()
    mock_client.return_value.chat.completions.create.return_value = [type("Chunk", (), {"choices": [Choice()]})()]
    response = Client().post("/api/chat/", data=json.dumps(payload()), content_type="application/json")
    body = b"".join(response.streaming_content).decode()
    assert response.status_code == 200
    assert '"type": "done"' in body
