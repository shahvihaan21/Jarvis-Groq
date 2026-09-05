"""Autonomous Daily Improvement Engine for Jarvis-Groq.

Executes a minor, high-quality, verified improvement on the repository.
Operates on the main branch, performs extensive pre- and post-validation,
and safely rolls back target files on any check failure.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from improvement_analyzer import analyze_repository
ROOT = Path(__file__).resolve().parent.parent
MINIMUM_SCORE = 55.0
LOG_FILE = ROOT / ".github" / "codex" / "improvement-log.md"
RULES_FILE = ROOT / ".github" / "codex" / "daily-improvement.md"

MAX_CHANGED_FILES = 5
MAX_CHANGED_LINES = 150
PROTECTED_PATHS = {
    ".env",
    ".env.example",
    "Procfile",
    "runtime.txt",
    "vercel.json",
}

SECRET_PATTERNS = [
    re.compile(r"gsk_[a-zA-Z0-9]{20,}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|password)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]"),
]


def run_command(args: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a local development command without shell interpretation."""
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def rollback(target_files: list[str]) -> None:
    """Safely revert changes for specific target files."""
    if not target_files:
        return
    print(f"Rolling back target files: {target_files}...")
    run_command(["git", "restore", "--staged", "--", *target_files], check=False)
    run_command(["git", "restore", "--", *target_files], check=False)
    for f in target_files:
        full_path = ROOT / f
        tracked = run_command(["git", "ls-files", "--", f], check=False).stdout.strip()
        if not tracked and full_path.exists():
            full_path.unlink()


def check_syntax(py_files: list[str]) -> None:
    """Validate Python AST syntax for modified python files."""
    for file_path in py_files:
        full_path = ROOT / file_path
        if full_path.exists() and full_path.suffix == ".py":
            ast.parse(full_path.read_text(encoding="utf-8"))


def run_test_suite() -> None:
    """Run Django system checks and the pytest test suite."""
    manage_py = ROOT / "backend" / "manage.py"
    if manage_py.exists():
        chk = run_command([sys.executable, str(manage_py), "check"], check=False)
        if chk.returncode != 0:
            raise RuntimeError(f"Django system check failed: {chk.stderr.strip() or chk.stdout.strip()}")

    pytest_cmd = [sys.executable, "-m", "pytest", "-q"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    proc = subprocess.run(
        pytest_cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Pytest failed: {proc.stdout.strip() or proc.stderr.strip()}")


def verify_security_and_limits(changed_files: list[str]) -> None:
    """Ensure no credentials, protected files, or excessive changes exist."""
    if len(changed_files) > MAX_CHANGED_FILES:
        raise RuntimeError(f"Exceeded file limit: {len(changed_files)} > {MAX_CHANGED_FILES}")

    for file_name in changed_files:
        if file_name in PROTECTED_PATHS:
            raise RuntimeError(f"Cannot modify protected file: {file_name}")
        if file_name.startswith(".github/workflows/"):
            raise RuntimeError(f"Cannot modify workflow files: {file_name}")

    diff_proc = run_command(["git", "diff", "--", *changed_files], check=False)
    diff_text = diff_proc.stdout
    total_lines = len([l for l in diff_text.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
    if total_lines > MAX_CHANGED_LINES:
        raise RuntimeError(f"Exceeded line limit: {total_lines} > {MAX_CHANGED_LINES}")

    for pattern in SECRET_PATTERNS:
        if pattern.search(diff_text):
            raise RuntimeError("Secret or credential detected in diff")


def apply_deprecation_warning_fix() -> tuple[str, list[str]]:
    """Improvement 1: Resolve JsonFormatter deprecation warning in settings."""
    settings_file = ROOT / "backend" / "ai" / "settings.py"
    content = settings_file.read_text(encoding="utf-8")
    target = '"()": "pythonjsonlogger.jsonlogger.JsonFormatter"'
    replacement = '"()": "pythonjsonlogger.json.JsonFormatter"'
    if target in content:
        new_content = content.replace(target, replacement)
        settings_file.write_text(new_content, encoding="utf-8")
        return "Upgrade JsonFormatter import in backend/ai/settings.py to eliminate deprecation warning", ["backend/ai/settings.py"]
    return "", []


def apply_health_endpoint_metadata() -> tuple[str, list[str]]:
    """Improvement 2: Add UTC ISO timestamp to health check API."""
    views_file = ROOT / "backend" / "todo" / "views.py"
    content = views_file.read_text(encoding="utf-8")
    if "from django.utils import timezone" not in content and 'datetime.timezone.utc' not in content:
        if 'import uuid' in content:
            content = content.replace("import uuid", "import datetime\nimport uuid")
        if '"status": "ok",' in content and '"timestamp":' not in content:
            content = content.replace(
                '"status": "ok",\n        "service": "jarvis-groq",',
                '"status": "ok",\n        "service": "jarvis-groq",\n        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),',
            )
            views_file.write_text(content, encoding="utf-8")
            return "Include UTC timestamp in /api/health/ readiness check", ["backend/todo/views.py"]
    return "", []


def apply_security_headers_hardening() -> tuple[str, list[str]]:
    """Improvement 3: Hardened Content-Type options and XSS protection headers."""
    settings_file = ROOT / "backend" / "ai" / "settings.py"
    content = settings_file.read_text(encoding="utf-8")
    if "SECURE_CONTENT_TYPE_NOSNIFF" not in content:
        target = 'DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"'
        addition = (
            'DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"\n\n'
            "# Browser security hardening\n"
            "SECURE_CONTENT_TYPE_NOSNIFF = True\n"
            "SECURE_BROWSER_XSS_FILTER = True\n"
        )
        if target in content:
            new_content = content.replace(target, addition)
            settings_file.write_text(new_content, encoding="utf-8")
            return "Harden HTTP security headers with nosniff and xss-filter settings", ["backend/ai/settings.py"]
    return "", []


def apply_tool_edge_case_tests() -> tuple[str, list[str]]:
    """Improvement 4: Add edge-case coverage for empty search and division by zero in tools."""
    tests_file = ROOT / "tests" / "test_tools.py"
    content = tests_file.read_text(encoding="utf-8")
    if "test_calculator_division_by_zero" not in content:
        addition = (
            "\n\ndef test_calculator_division_by_zero():\n"
            "    with pytest.raises(ToolExecutionError):\n"
            "        execute_tool('calculator', {'expression': '10 / 0'})\n"
            "\n\ndef test_repository_search_empty_query():\n"
            "    res = execute_tool('repository_search', {'query': ''})\n"
            "    assert res['status'] == 'success'\n"
            "    assert 'files' in res['result']\n"
        )
        tests_file.write_text(content + addition, encoding="utf-8")
        return "Add edge-case unit tests for calculator division by zero and empty repo search", ["tests/test_tools.py"]
    return "", []


CATALOG_IMPROVEMENTS: list[Callable[[], tuple[str, list[str]]]] = [
    "Upgrade JsonFormatter import to eliminate deprecation warning": apply_deprecation_warning_fix,
    "Include UTC timestamp in the health check response": apply_health_endpoint_metadata,
    "Harden HTTP security headers with nosniff and XSS protection": apply_security_headers_hardening,
    "Add edge-case tests for calculator and empty repository search": apply_tool_edge_case_tests,
}


def execute_catalog_improvement() -> tuple[str, list[str]]:
    """Find and execute the next applicable minor improvement from the catalog."""
    log_content = LOG_FILE.read_text(encoding="utf-8") if LOG_FILE.exists() else ""
    for improvement_func in CATALOG_IMPROVEMENTS:
        title, files = improvement_func()
        if title and title not in log_content:
            return title, files
        if title and title in log_content:
            rollback(files)
    return "", []


def update_log(title: str, target_files: list[str]) -> None:
    """Record verified improvement to improvement-log.md."""
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    files_str = ", ".join(f"`{f}`" for f in target_files)
    entry = f"| {today} | {title} | {files_str} | Verified |\n"
    if LOG_FILE.exists():
        content = LOG_FILE.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        LOG_FILE.write_text(content + entry, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous Daily Improvement Engine")
    parser.add_argument("--dry-run", action="store_true", help="Validate without committing or pushing")
    parser.add_argument("--check-only", action="store_true", help="Run system test suite and verify health")
    parser.add_argument("--no-push", action="store_true", help="Commit changes but do not push to remote")
    args = parser.parse_args()

    print("=== Jarvis Autonomous Daily Improvement Engine ===")
    print("Checking repository state and baseline tests...")

    try:
        run_test_suite()
        print("Baseline test suite passed successfully.")
    except Exception as e:
        print(f"Error during baseline checks: {e}", file=sys.stderr)
        return 1

    if args.check_only:
        print("Repository is in a healthy, fully verified state.")
        return 0

    candidate, candidates = select_improvement()
    print(f"Candidates discovered: {len(candidates)}")
    if not candidate:
        print("No significant safe improvement found today. Repository unchanged.")
        return 0
    title = candidate["title"]
    target_files = candidate["affected_files"]
    print(f"Selected improvement: {title} (score {candidate['score']:.2f})")
    print(f"Target files: {target_files}")

    try:
        check_syntax([f for f in target_files if f.endswith(".py")])
        verify_security_and_limits(target_files)
        run_test_suite()
        update_log(candidate, target_files, "Django check + pytest passed")
        verify_security_and_limits(target_files + [str(LOG_FILE.relative_to(ROOT))])
        print("Post-improvement tests and improvement-log validation passed successfully.")
    except Exception as e:
        print(f"Validation failed after improvement: {e}. Initiating rollback...", file=sys.stderr)
        rollback(target_files + ([str(LOG_FILE.relative_to(ROOT))] if LOG_FILE.exists() else []))
        return 1

    if args.dry_run:
        print("Dry run active: rolling back applied changes...")
        rollback(target_files)
        print("Dry run completed cleanly.")
        return 0

    # Commit and log
    update_log(title, target_files)
    run_command(["git", "add", *target_files, str(LOG_FILE.relative_to(ROOT))])
    commit_msg = f"chore: daily improvement - {title} [skip ci]"
    run_command(["git", "commit", "-m", commit_msg])
    print(f"Committed improvement: {commit_msg}")

    if not args.no_push:
        print("Pushing verified improvement to origin main...")
        res = run_command(["git", "push", "origin", "main"], check=False)
        if res.returncode != 0:
            print(f"Failed to push changes: {res.stderr.strip()}", file=sys.stderr)
            return 1
        print("Push successful.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
