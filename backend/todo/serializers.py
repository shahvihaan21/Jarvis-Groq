"""Typed request/response shapes for future stateful extensions."""

from typing import Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(TypedDict):
    message: str
    history: list[ChatMessage]
    request_id: str
