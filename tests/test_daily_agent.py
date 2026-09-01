"""Unit tests for daily_agent helper functions and security restrictions."""

import json
from pathlib import Path
import pytest

from scripts.daily_agent import (
    parse_proposal,
    protected_change,
    is_sensitive_or_unnecessary,
    redact_sensitive_content,
    ROOT,
)


def test_parse_proposal_valid_no_improvement():
    payload = {
        "no_improvement": True,
        "improvement": "",
        "why": "Repository is in optimal state.",
        "files": [],
        "implementation": "",
        "tests": [],
        "patch": "",
    }
    result = parse_proposal(json.dumps(payload))
    assert result["no_improvement"] is True
    assert result["why"] == "Repository is in optimal state."


def test_parse_proposal_valid_with_improvement():
    payload = {
        "no_improvement": False,
        "improvement": "Fix typo in docstring",
        "why": "Improves code clarity",
        "files": ["backend/todo/utils.py"],
        "implementation": "Correct spelling in utils.py",
        "tests": ["pytest"],
        "patch": "--- a/backend/todo/utils.py\n+++ b/backend/todo/utils.py\n@@ -1 +1 @@\n",
    }
    result = parse_proposal(json.dumps(payload))
    assert result["no_improvement"] is False
    assert result["improvement"] == "Fix typo in docstring"


def test_parse_proposal_strips_markdown_fences():
    payload = {
        "no_improvement": True,
        "improvement": "",
        "why": "No changes needed",
        "files": [],
        "implementation": "",
        "tests": [],
        "patch": "",
    }
    raw = f"```json\n{json.dumps(payload)}\n```"
    result = parse_proposal(raw)
    assert result["no_improvement"] is True


def test_parse_proposal_missing_field_raises():
    payload = {
        "no_improvement": False,
        "improvement": "Fix something",
        # missing 'why', 'files', etc.
    }
    with pytest.raises(RuntimeError, match="missing required fields"):
        parse_proposal(json.dumps(payload))


def test_protected_change():
    assert protected_change(".github/workflows/ci.yml") is True
    assert protected_change(".github/codex/daily-improvement.md") is True
    assert protected_change("scripts/daily_agent.py") is True
    assert protected_change("vercel.json") is True
    assert protected_change("Procfile") is True
    assert protected_change(".env") is True
    assert protected_change("backend/todo/utils.py") is False


def test_is_sensitive_or_unnecessary():
    assert is_sensitive_or_unnecessary(ROOT / ".env") is True
    assert is_sensitive_or_unnecessary(ROOT / "secrets.json") is True
    assert is_sensitive_or_unnecessary(ROOT / "backend" / "todo" / "views.py") is False


def test_redact_sensitive_content():
    content = "OPENROUTER_API_KEY = sk-or-v1-1234567890abcdef1234567890"
    redacted = redact_sensitive_content(content)
    assert "sk-or-v1-" not in redacted
    assert "[REDACTED" in redacted
