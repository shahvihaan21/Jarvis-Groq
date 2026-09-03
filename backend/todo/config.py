"""Central configuration for the stateless Jarvis provider integration."""

import os

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "45"))
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "12"))
MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "8000"))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(256 * 1024)))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are Jarvis AI, a highly intelligent, fast, and helpful technical AI assistant. "
    "Answer clearly, accurately, and precisely. Use Markdown for formatting and code blocks."
)

