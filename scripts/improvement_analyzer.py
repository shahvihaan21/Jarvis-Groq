'''Read-only repository analysis for the daily improvement engine.

This module only reads repository files. It never writes, installs packages, or invokes
shell commands, so candidate discovery cannot mutate the baseline before selection.
'''
from __future__ import annotations
import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules", "build", "dist", "staticfiles"}
PROTECTED_PREFIXES = (".github/workflows/",)
PROTECTED_FILES = {".env", ".env.example", "Procfile", "runtime.txt", "vercel.json"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".ini", ".js", ".html", ".css"}


def _safe(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return rel not in PROTECTED_FILES and not rel.startswith(PROTECTED_PREFIXES)


def _files() -> list[Path]:
    result = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts) or not _safe(path):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 500_000:
            result.append(path)
    return result

def _candidate(title: str, category: str, description: str, files: list[str], impact: int, risk: int, confidence: int, reason: str, *, test_value: int = 0, reliability: int = 0, maintainability: int = 0, security: int = 0) -> dict[str, Any]:
    # High impact/reliability/security/test value and confidence are rewarded; risk is a penalty.
    score = round(0.24 * impact + 0.16 * reliability + 0.14 * security + 0.14 * maintainability + 0.14 * test_value + 0.12 * confidence - 0.06 * risk, 2)
    return {"title": title, "category": category, "description": description, "affected_files": files, "estimated_impact": impact, "risk": risk, "confidence": confidence, "score": score, "reason": reason}


def analyze_repository(root: Path = ROOT) -> list[dict[str, Any]]:
    'Return evidence-backed candidates without changing the repository.'
    global ROOT
    previous_root = ROOT
    ROOT = root.resolve()
    try:
        files = _files()
        contents: dict[str, str] = {}
        for path in files:
            try:
                contents[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        candidates: list[dict[str, Any]] = []
        settings = contents.get("backend/ai/settings.py", "")
        views = contents.get("backend/todo/views.py", "")
        tool_tests = contents.get("tests/test_tools.py", "")
        if 'pythonjsonlogger.jsonlogger.JsonFormatter' in settings:
            candidates.append(_candidate("Upgrade JsonFormatter import to eliminate deprecation warning", "reliability", "The settings file references the deprecated python-json-logger formatter path.", ["backend/ai/settings.py"], 64, 10, 99, "A concrete deprecated import path was found in the live settings.", reliability=80, maintainability=75))
        if '"status": "ok"' in views and '"timestamp":' not in views:
            candidates.append(_candidate("Include UTC timestamp in the health check response", "reliability", "The health response has no machine-readable UTC timestamp for diagnosing stale or delayed responses.", ["backend/todo/views.py"], 68, 18, 94, "The health endpoint was found without timestamp metadata.", reliability=88, maintainability=60))
        if "SECURE_CONTENT_TYPE_NOSNIFF" not in settings:
            candidates.append(_candidate("Harden HTTP security headers with nosniff and XSS protection", "security", "Django security middleware is enabled but explicit browser response hardening is absent.", ["backend/ai/settings.py"], 72, 20, 90, "The settings contain no SECURE_CONTENT_TYPE_NOSNIFF configuration.", security=90, reliability=65))
        if "test_calculator_division_by_zero" not in tool_tests:
            candidates.append(_candidate("Add edge-case tests for calculator and empty repository search", "testing", "Important calculator and search boundary behavior is not represented in the tool test suite.", ["tests/test_tools.py"], 78, 8, 97, "The named edge-case tests are absent from the existing tests.", test_value=98, reliability=82))
        todo_hits = []
        for name, text in contents.items():
            for match in re.finditer(r"\b(TODO|FIXME)\b[^\n]*", text, re.IGNORECASE):
                todo_hits.append((name, match.group(0).strip()))
        if todo_hits:
            files_hit = sorted({name for name, _ in todo_hits})[:5]
            candidates.append(_candidate("Review outstanding TODO/FIXME items", "maintainability", f"Found {len(todo_hits)} explicit TODO/FIXME marker(s), including: {todo_hits[0][1][:100]}", files_hit, 48, 28, 86, "Markers in source and documentation indicate deferred maintenance work.", maintainability=86))
        for name, text in contents.items():
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            long_functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.end_lineno or node.lineno) - node.lineno + 1 > 80]
            if long_functions:
                candidates.append(_candidate(f"Review oversized functions in {name}", "maintainability", f"Function(s) {', '.join(long_functions[:3])} exceed 80 lines and merit focused decomposition or tests.", [name], 46, 35, 82, "AST inspection found unusually large functions; no automatic rewrite is proposed.", maintainability=88, test_value=45))
        return sorted(candidates, key=lambda item: (-item["score"], item["title"]))
    finally:
        ROOT = previous_root

def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jarvis repository improvement analyzer")
    parser.add_argument("--json", action="store_true", help="Print candidates as JSON")
    args = parser.parse_args()
    candidates = analyze_repository()
    if args.json:
        print(json.dumps(candidates, indent=2))
    else:
        print(f"Candidates discovered: {len(candidates)}")
        for item in candidates:
            print(f"- {item['score']:.2f}: {item['title']} [{item['category']}] ({', '.join(item['affected_files'])})")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
