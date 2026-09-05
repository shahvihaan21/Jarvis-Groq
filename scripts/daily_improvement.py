
"""Autonomous Daily Improvement Engine for Jarvis-Groq.

Executes one small, high-quality, verified improvement on the repository.

Safety model:
- Requires a clean working tree before making changes.
- Runs baseline validation before every improvement.
- Applies exactly one catalog improvement.
- Validates syntax, security, limits, Django checks and pytest.
- Automatically restores the exact baseline if validation fails.
- Failed improvements are rejected cleanly and do not push.
- Only verified improvements are committed and pushed.
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
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
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
    re.compile(
        r"-----BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) KEY-----"
    ),
    re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|password)"
        r"\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]"
    ),
]


def run_command(
    args: list[str],
    cwd: Path = ROOT,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Execute a command without shell interpretation."""
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        env=env,
    )


def get_git_status() -> str:
    """Return porcelain repository status."""
    return run_command(
        ["git", "status", "--porcelain"],
        check=True,
    ).stdout.strip()


def get_current_commit() -> str:
    """Return the current HEAD SHA."""
    return run_command(
        ["git", "rev-parse", "HEAD"],
        check=True,
    ).stdout.strip()


def ensure_clean_worktree() -> None:
    """Require a clean repository before autonomous modification."""
    status = get_git_status()

    if status:
        raise RuntimeError(
            "Repository is not clean. "
            "Autonomous improvement aborted to protect existing changes:\n"
            f"{status}"
        )


def rollback(baseline_commit: str) -> bool:
    """Restore the repository to the exact baseline commit."""
    print(f"Rolling back to baseline {baseline_commit[:12]}...")

    try:
        # Restore all tracked files to the exact baseline.
        result = run_command(
            ["git", "reset", "--hard", baseline_commit],
            check=False,
        )

        if result.returncode != 0:
            print(
                f"Git reset failed: "
                f"{result.stderr.strip() or result.stdout.strip()}",
                file=sys.stderr,
            )
            return False

        # Remove untracked files created by the improvement.
        clean_result = run_command(
            ["git", "clean", "-fd"],
            check=False,
        )

        if clean_result.returncode != 0:
            print(
                f"Git clean failed: "
                f"{clean_result.stderr.strip() or clean_result.stdout.strip()}",
                file=sys.stderr,
            )
            return False

        # Verify rollback actually restored the repository.
        final_commit = get_current_commit()
        final_status = get_git_status()

        if final_commit != baseline_commit:
            print(
                "Rollback verification failed: HEAD does not match baseline.",
                file=sys.stderr,
            )
            return False

        if final_status:
            print(
                "Rollback verification failed: working tree is not clean:\n"
                f"{final_status}",
                file=sys.stderr,
            )
            return False

        print("Rollback completed and verified successfully.")
        return True

    except Exception as exc:
        print(f"Rollback failed unexpectedly: {exc}", file=sys.stderr)
        return False


def check_syntax(py_files: list[str]) -> None:
    """Validate Python syntax for modified Python files."""
    for file_path in py_files:
        full_path = ROOT / file_path

        if full_path.exists() and full_path.suffix == ".py":
            ast.parse(full_path.read_text(encoding="utf-8"))


def run_test_suite() -> None:
    """Run Django system checks and the complete pytest suite."""
    manage_py = ROOT / "backend" / "manage.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")

    if manage_py.exists():
        chk = run_command(
            [sys.executable, str(manage_py), "check"],
            check=False,
            env=env,
        )

        if chk.returncode != 0:
            raise RuntimeError(
                "Django system check failed:\n"
                f"{chk.stderr.strip() or chk.stdout.strip()}"
            )

    proc = run_command(
        [sys.executable, "-m", "pytest", "-q"],
        check=False,
        env=env,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "Pytest failed:\n"
            f"{proc.stdout.strip() or proc.stderr.strip()}"
        )


def verify_security_and_limits(changed_files: list[str]) -> None:
    """Ensure changes stay within safety and size limits."""
    if len(changed_files) > MAX_CHANGED_FILES:
        raise RuntimeError(
            f"Exceeded file limit: "
            f"{len(changed_files)} > {MAX_CHANGED_FILES}"
        )

    for file_name in changed_files:
        if file_name in PROTECTED_PATHS:
            raise RuntimeError(
                f"Cannot modify protected file: {file_name}"
            )

        if file_name.startswith(".github/workflows/"):
            raise RuntimeError(
                f"Cannot modify workflow files: {file_name}"
            )

    diff_proc = run_command(
        ["git", "diff", "--", *changed_files],
        check=False,
    )

    diff_text = diff_proc.stdout

    total_lines = len(
        [
            line
            for line in diff_text.splitlines()
            if line.startswith(("+", "-"))
            and not line.startswith(("+++", "---"))
        ]
    )

    if total_lines > MAX_CHANGED_LINES:
        raise RuntimeError(
            f"Exceeded line limit: "
            f"{total_lines} > {MAX_CHANGED_LINES}"
        )

    for pattern in SECRET_PATTERNS:
        if pattern.search(diff_text):
            raise RuntimeError(
                "Secret or credential detected in diff"
            )


def apply_deprecation_warning_fix() -> tuple[str, list[str]]:
    """Improvement 1: Resolve JsonFormatter deprecation warning."""
    settings_file = ROOT / "backend" / "ai" / "settings.py"

    content = settings_file.read_text(encoding="utf-8")

    target = '"()": "pythonjsonlogger.jsonlogger.JsonFormatter"'
    replacement = '"()": "pythonjsonlogger.json.JsonFormatter"'

    if target in content:
        settings_file.write_text(
            content.replace(target, replacement),
            encoding="utf-8",
        )

        return (
            "Upgrade JsonFormatter import in backend/ai/settings.py "
            "to eliminate deprecation warning",
            ["backend/ai/settings.py"],
        )

    return "", []


def apply_health_endpoint_metadata() -> tuple[str, list[str]]:
    """Improvement 2: Add UTC ISO timestamp to health check."""
    views_file = ROOT / "backend" / "todo" / "views.py"

    content = views_file.read_text(encoding="utf-8")

    if (
        "from django.utils import timezone" not in content
        and "datetime.timezone.utc" not in content
    ):
        if "import uuid" in content:
            content = content.replace(
                "import uuid",
                "import datetime\nimport uuid",
            )

        if (
            '"status": "ok",' in content
            and '"timestamp":' not in content
        ):
            content = content.replace(
                '"status": "ok",\n'
                '        "service": "jarvis-groq",',
                '"status": "ok",\n'
                '        "service": "jarvis-groq",\n'
                '        "timestamp": '
                'datetime.datetime.now('
                'datetime.timezone.utc'
                ').isoformat(),',
            )

            views_file.write_text(
                content,
                encoding="utf-8",
            )

            return (
                "Include UTC timestamp in /api/health/ readiness check",
                ["backend/todo/views.py"],
            )

    return "", []


def apply_security_headers_hardening() -> tuple[str, list[str]]:
    """Improvement 3: Harden browser security headers."""
    settings_file = ROOT / "backend" / "ai" / "settings.py"

    content = settings_file.read_text(encoding="utf-8")

    if "SECURE_CONTENT_TYPE_NOSNIFF" not in content:
        target = (
            'DEFAULT_AUTO_FIELD = '
            '"django.db.models.BigAutoField"'
        )

        addition = (
            'DEFAULT_AUTO_FIELD = '
            '"django.db.models.BigAutoField"\n\n'
            "# Browser security hardening\n"
            "SECURE_CONTENT_TYPE_NOSNIFF = True\n"
            "SECURE_BROWSER_XSS_FILTER = True\n"
        )

        if target in content:
            settings_file.write_text(
                content.replace(target, addition),
                encoding="utf-8",
            )

            return (
                "Harden HTTP security headers with "
                "nosniff and xss-filter settings",
                ["backend/ai/settings.py"],
            )

    return "", []


def apply_tool_edge_case_tests() -> tuple[str, list[str]]:
    """Improvement 4: Add valid edge-case tests for tools."""
    tests_file = ROOT / "tests" / "test_tools.py"

    content = tests_file.read_text(encoding="utf-8")

    if "test_calculator_division_by_zero" not in content:
        addition = """
        
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
"""

        tests_file.write_text(
            content.rstrip() + addition,
            encoding="utf-8",
        )

        return (
            "Add valid edge-case unit tests for calculator "
            "division by zero and repository search validation",
            ["tests/test_tools.py"],
        )

    return "", []


CATALOG_IMPROVEMENTS: list[
    Callable[[], tuple[str, list[str]]]
] = [
    apply_deprecation_warning_fix,
    apply_health_endpoint_metadata,
    apply_security_headers_hardening,
    apply_tool_edge_case_tests,
]


def execute_catalog_improvement() -> tuple[str, list[str]]:
    """Find and execute the next applicable catalog improvement."""
    log_content = (
        LOG_FILE.read_text(encoding="utf-8")
        if LOG_FILE.exists()
        else ""
    )

    for improvement_func in CATALOG_IMPROVEMENTS:
        title, files = improvement_func()

        if not title:
            continue

        if title in log_content:
            # This improvement was already completed.
            # Undo the candidate mutation before trying the next one.
            rollback(get_current_commit())
            continue

        return title, files

    return "", []


def update_log(title: str, target_files: list[str]) -> None:
    """Record a verified improvement."""
    today = datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y-%m-%d")

    files_str = ", ".join(
        f"`{file_name}`"
        for file_name in target_files
    )

    entry = (
        f"| {today} | {title} | "
        f"{files_str} | Verified |\n"
    )

    if LOG_FILE.exists():
        content = LOG_FILE.read_text(
            encoding="utf-8"
        )

        if not content.endswith("\n"):
            content += "\n"

        LOG_FILE.write_text(
            content + entry,
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autonomous Daily Improvement Engine"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without committing or pushing",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run system validation only",
    )

    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit changes but do not push",
    )

    args = parser.parse_args()

    print(
        "=== Jarvis Autonomous Daily Improvement Engine ==="
    )

    # ---------------------------------------------------------
    # 1. Require a clean starting point.
    # ---------------------------------------------------------

    print("Checking repository state...")

    try:
        ensure_clean_worktree()
    except Exception as exc:
        print(
            f"Repository safety check failed: {exc}",
            file=sys.stderr,
        )
        return 1

    baseline_commit = get_current_commit()

    print(
        f"Baseline commit: {baseline_commit}"
    )

    # ---------------------------------------------------------
    # 2. Baseline validation.
    # ---------------------------------------------------------

    print("Running baseline tests...")

    try:
        run_test_suite()
        print(
            "Baseline test suite passed successfully."
        )
    except Exception as exc:
        print(
            f"Baseline validation failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if args.check_only:
        print(
            "Repository is healthy and fully verified."
        )
        return 0

    # ---------------------------------------------------------
    # 3. Apply exactly one improvement.
    # ---------------------------------------------------------

    try:
        title, target_files = execute_catalog_improvement()
    except Exception as exc:
        print(
            f"Improvement generation failed: {exc}",
            file=sys.stderr,
        )

        rollback(baseline_commit)
        return 1

    if not title:
        print(
            "All catalog improvements are already applied."
        )
        print(
            "Performing final system health check..."
        )

        try:
            run_test_suite()
        except Exception as exc:
            print(
                f"Health check failed: {exc}",
                file=sys.stderr,
            )
            return 1

        print(
            "Daily repository maintenance completed."
        )
        return 0

    print(
        f"Applying minor improvement: {title}"
    )
    print(
        f"Target files: {target_files}"
    )

    # ---------------------------------------------------------
    # 4. Validate the improvement.
    # ---------------------------------------------------------

    try:
        check_syntax(
            [
                file_name
                for file_name in target_files
                if file_name.endswith(".py")
            ]
        )

        verify_security_and_limits(
            target_files
        )

        run_test_suite()

        print(
            "Post-improvement validation passed."
        )

    except Exception as exc:
        print(
            f"Validation failed after improvement: {exc}",
            file=sys.stderr,
        )

        print(
            "Rejecting improvement and restoring baseline..."
        )

        rollback_success = rollback(
            baseline_commit
        )

        if rollback_success:
            print(
                "Improvement rejected safely. "
                "Repository remains unchanged."
            )

            # IMPORTANT:
            # A rejected improvement is not a broken repository.
            return 0

        print(
            "CRITICAL: automatic rollback failed. "
            "Manual intervention required.",
            file=sys.stderr,
        )

        return 1

    # ---------------------------------------------------------
    # 5. Dry run.
    # ---------------------------------------------------------

    if args.dry_run:
        print(
            "Dry run active. Rolling back validated improvement..."
        )

        if rollback(baseline_commit):
            print(
                "Dry run completed successfully."
            )
            return 0

        print(
            "Dry-run rollback failed.",
            file=sys.stderr,
        )
        return 1

    # ---------------------------------------------------------
    # 6. Record verified improvement.
    # ---------------------------------------------------------

    try:
        update_log(
            title,
            target_files,
        )

        run_command(
            [
                "git",
                "add",
                *target_files,
                str(LOG_FILE.relative_to(ROOT)),
            ]
        )

        # Verify staged changes before committing.
        staged = run_command(
            ["git", "diff", "--cached", "--name-only"],
            check=True,
        ).stdout.strip()

        if not staged:
            print(
                "No staged changes found. Nothing to commit."
            )
            return 0

        commit_msg = (
            f"chore: daily improvement - "
            f"{title} [skip ci]"
        )

        run_command(
            ["git", "commit", "-m", commit_msg]
        )

        print(
            f"Committed verified improvement: {commit_msg}"
        )

    except Exception as exc:
        print(
            f"Commit preparation failed: {exc}",
            file=sys.stderr,
        )

        rollback(baseline_commit)
        return 1

    # ---------------------------------------------------------
    # 7. Push only after successful validation + commit.
    # ---------------------------------------------------------

    if not args.no_push:
        print(
            "Pushing verified improvement to origin main..."
        )

        result = run_command(
            ["git", "push", "origin", "main"],
            check=False,
        )

        if result.returncode != 0:
            print(
                "Push failed. The verified commit remains "
                "locally available.",
                file=sys.stderr,
            )

            print(
                result.stderr.strip()
                or result.stdout.strip(),
                file=sys.stderr,
            )

            return 1

        print("Push successful.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
