"""
Unit and API integration tests for Controlled Tool Architecture (backend/todo/tools.py).
"""

import pytest
from django.test import Client
from django.urls import reverse
from todo.tools import execute_tool, ToolExecutionError, get_registered_tools_schema


def test_calculator_valid():
    res = execute_tool("calculator", {"expression": "25 * 4 + 10"})
    assert res["status"] == "success"
    assert res["result"]["result"] == 110.0


def test_calculator_invalid_syntax():
    with pytest.raises(ToolExecutionError):
        execute_tool("calculator", {"expression": "25 * * 4"})


def test_calculator_security_boundary():
    with pytest.raises(ToolExecutionError):
        execute_tool("calculator", {"expression": "__import__('os').system('dir')"})


def test_repository_search_valid():
    res = execute_tool("repository_search", {"query": "views"})
    assert res["status"] == "success"
    assert res["result"]["count"] > 0
    assert any("views.py" in f for f in res["result"]["files"])


def test_file_inspection_valid():
    res = execute_tool("file_inspection", {"file_path": "backend/todo/urls.py"})
    assert res["status"] == "success"
    assert "urlpatterns" in res["result"]["content"]


def test_file_inspection_path_traversal_blocked():
    with pytest.raises(ToolExecutionError, match="Access denied"):
        execute_tool("file_inspection", {"file_path": "../../../Windows/System32/drivers/etc/hosts"})


def test_project_metadata():
    res = execute_tool("project_metadata", {})
    assert res["status"] == "success"
    assert res["result"]["project_name"] == "Jarvis-Groq"


def test_tools_api_get_schemas():
    response = Client().get(reverse("tools_api"))
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "calculator" in tool_names
    assert "repository_search" in tool_names


def test_tools_api_post_execute():
    response = Client().post(
        reverse("tools_api"),
        data={"tool": "calculator", "arguments": {"expression": "50 + 50"}},
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["result"]["result"] == 100.0
        
def test_calculator_division_by_zero():
    with pytest.raises(ToolExecutionError):
        execute_tool(
            "calculator",
            {"expression": "10 / 0"},
        )


def test_repository_search_empty_query():
    with pytest.raises(
        ToolExecutionError,
        match="Search query must be between 1 and 100 characters",
    ):
        execute_tool(
            "repository_search",
            {"query": ""},
        )


def test_repository_search_query_too_long():
    with pytest.raises(
        ToolExecutionError,
        match="Search query must be between 1 and 100 characters",
    ):
        execute_tool(
            "repository_search",
            {"query": "x" * 101},
        )
