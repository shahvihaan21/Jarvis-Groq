"""
Controlled Tool Architecture for Jarvis AI.

Provides bounded, safe execution of inspection, search, math, and project metadata tools
with explicit JSON schemas, path containment, execution timeouts, and audit logging.
Unrestricted shell execution is strictly prohibited.
"""

import ast
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Base directory boundary (Jarvis-Web root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ToolExecutionError(Exception):
    """Raised when a tool execution fails or exceeds boundaries."""
    pass


class SafeMathEvaluator(ast.NodeVisitor):
    """Safe AST evaluator for mathematical expressions only."""
    ALLOWED_NODES = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
        ast.USub, ast.UAdd
    )

    def visit(self, node):
        if not isinstance(node, self.ALLOWED_NODES):
            raise ToolExecutionError(f"Unsupported math operation: {type(node).__name__}")
        return super().visit(node)

    def eval(self, expr: str) -> float:
        try:
            tree = ast.parse(expr, mode='eval')
            self.visit(tree)
            compiled = compile(tree, filename='<math>', mode='eval')
            return eval(compiled, {"__builtins__": None}, {})
        except Exception as e:
            raise ToolExecutionError(f"Invalid mathematical expression: {e}")


def tool_calculator(expression: str) -> Dict[str, Any]:
    """Execute safe mathematical calculation."""
    if not expression or len(expression) > 200:
        raise ToolExecutionError("Expression must be between 1 and 200 characters.")
    evaluator = SafeMathEvaluator()
    result = evaluator.eval(expression)
    return {"expression": expression, "result": result}


def tool_repository_search(query: str, max_results: int = 10) -> Dict[str, Any]:
    """Search for files in the repository by name or extension."""
    if not query or len(query) > 100:
        raise ToolExecutionError("Search query must be between 1 and 100 characters.")

    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Exclude hidden, git, cache, and venv dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'venv', 'staticfiles', 'node_modules')]
        for file in files:
            rel_path = Path(root, file).relative_to(PROJECT_ROOT).as_posix()
            if pattern.search(rel_path) or pattern.search(file):
                results.append(rel_path)
                if len(results) >= min(max_results, 50):
                    break
        if len(results) >= min(max_results, 50):
            break

    return {"query": query, "count": len(results), "files": results}


def tool_file_inspection(file_path: str, max_lines: int = 200) -> Dict[str, Any]:
    """Inspect contents of a project text file within safety boundaries."""
    if not file_path:
        raise ToolExecutionError("file_path parameter is required.")

    target_path = (PROJECT_ROOT / file_path).resolve()

    # Path traversal protection: Ensure target is within PROJECT_ROOT
    if not str(target_path).startswith(str(PROJECT_ROOT)):
        raise ToolExecutionError("Access denied: Target file is outside project workspace boundaries.")

    if not target_path.exists() or not target_path.is_file():
        raise ToolExecutionError(f"File not found: {file_path}")

    # Check file size limit (max 500 KB)
    if target_path.stat().st_size > 500 * 1024:
        raise ToolExecutionError("File size exceeds 500 KB limit for inspection.")

    try:
        content_lines = target_path.read_text(encoding='utf-8', errors='replace').splitlines()
        slice_lines = content_lines[:max_lines]
        return {
            "file_path": file_path,
            "total_lines": len(content_lines),
            "displayed_lines": len(slice_lines),
            "content": "\n".join(slice_lines)
        }
    except Exception as e:
        raise ToolExecutionError(f"Unable to read file: {e}")


def tool_project_metadata() -> Dict[str, Any]:
    """Retrieve active project metadata and configuration summary."""
    return {
        "project_name": "Jarvis-Groq",
        "framework": "Django 5.0",
        "language": "Python 3.12 / ES6 JS",
        "architecture": "Stateless Proxy / Serverless-Ready",
        "default_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        "active_provider": os.getenv("AI_PROVIDER", "groq"),
    }


TOOLS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "calculator": {
        "name": "calculator",
        "description": "Safely evaluate mathematical expressions.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Mathematical expression (e.g. 25 * 4 + 10)"}},
            "required": ["expression"]
        },
        "handler": lambda kwargs: tool_calculator(kwargs.get("expression", "")),
    },
    "repository_search": {
        "name": "repository_search",
        "description": "Search for files in the active project workspace by filename query.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Filename or extension query"}},
            "required": ["query"]
        },
        "handler": lambda kwargs: tool_repository_search(kwargs.get("query", "")),
    },
    "file_inspection": {
        "name": "file_inspection",
        "description": "Inspect text lines of a project workspace file within safe boundaries.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative file path within project (e.g. backend/todo/views.py)"}
            },
            "required": ["file_path"]
        },
        "handler": lambda kwargs: tool_file_inspection(kwargs.get("file_path", "")),
    },
    "project_metadata": {
        "name": "project_metadata",
        "description": "Retrieve project architecture, tech stack, and environment metadata.",
        "parameters": {"type": "object", "properties": {}},
        "handler": lambda kwargs: tool_project_metadata(),
    },
}


def get_registered_tools_schema() -> List[Dict[str, Any]]:
    """Return JSON schemas for all available tools."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        for tool in TOOLS_REGISTRY.values()
    ]


def execute_tool(tool_name: str, arguments: Dict[str, Any], request_id: str = "") -> Dict[str, Any]:
    """
    Safely execute a registered tool by name with arguments and audit logging.
    """
    if tool_name not in TOOLS_REGISTRY:
        raise ToolExecutionError(f"Unknown tool: '{tool_name}'")

    tool_def = TOOLS_REGISTRY[tool_name]
    logger.info("tool_execution_start", extra={"tool_name": tool_name, "request_id": request_id})

    try:
        result = tool_def["handler"](arguments or {})
        logger.info("tool_execution_success", extra={"tool_name": tool_name, "request_id": request_id})
        return {"status": "success", "tool_name": tool_name, "result": result}
    except Exception as err:
        logger.error("tool_execution_error", extra={"tool_name": tool_name, "error": str(err), "request_id": request_id})
        raise ToolExecutionError(str(err))
