"""
Jarvis-Groq Autonomous Daily Improvement Engine.

Design goals:
- Operates directly on main.
- One verified improvement per run.
- Never pushes an unvalidated change.
- Automatically rolls back failed changes.
- Skips already-applied improvements.
- Keeps an improvement history.
- Performs baseline and post-change validation.
- Never modifies GitHub workflow files.
- Never modifies protected deployment/secrets files.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent

LOG_FILE = ROOT / ".github" / "codex" / "improvement-log.md"

MAX_CHANGED_FILES = 5
MAX_CHANGED_LINES = 150

PROTECTED_PATHS = {
    ".env",
    ".env.example",
    "Procfile",
    "runtime.txt",
    "vercel.json",
}

PROTECTED_PREFIXES = (
    ".github/workflows/",
    ".git/",
)

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


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def run_command(
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def repository_is_clean() -> bool:
    result = run_command(
        ["git", "status", "--porcelain"],
        check=False,
    )
    return not result.stdout.strip()


def rollback_to_baseline(baseline_commit: str) -> bool:
    """
    Restore the repository to the exact commit that existed
    before the improvement was attempted.
    """
    print(f"Rolling back to baseline {baseline_commit}...")

    reset = run_command(
        ["git", "reset", "--hard", baseline_commit],
        check=False,
    )

    clean = run_command(
        ["git", "clean", "-fd"],
        check=False,
    )

    head = run_command(
        ["git", "rev-parse", "HEAD"],
        check=False,
    )

    status = run_command(
        ["git", "status", "--porcelain"],
        check=False,
    )

    success = (
        reset.returncode == 0
        and clean.returncode == 0
        and head.stdout.strip() == baseline_commit
        and not status.stdout.strip()
    )

    if success:
        print("Rollback completed successfully.")
    else:
        print(
            "CRITICAL: rollback verification failed.",
            file=sys.stderr,
        )

    return success


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def run_test_suite() -> None:
    """
    Run Django checks and the complete pytest suite.
    """
    manage_py = ROOT / "backend" / "manage.py"

    if manage_py.exists():
        result = run_command(
            [sys.executable, str(manage_py), "check"],
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Django system check failed:\n"
                + (result.stderr.strip() or result.stdout.strip())
            )

    result = run_command(
        [sys.executable, "-m", "pytest", "-q"],
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Pytest failed:\n"
            + (result.stdout.strip() or result.stderr.strip())
        )


def check_syntax(files: list[str]) -> None:
    """
    Parse every modified Python file using the AST parser.
    """
    for file_name in files:
        path = ROOT / file_name

        if not path.exists():
            continue

        if path.suffix != ".py":
            continue

        ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )


def verify_security_and_limits(changed_files: list[str]) -> None:
    """
    Reject dangerous or excessively large modifications.
    """
    unique_files = sorted(set(changed_files))

    if len(unique_files) > MAX_CHANGED_FILES:
        raise RuntimeError(
            f"Too many changed files: "
            f"{len(unique_files)} > {MAX_CHANGED_FILES}"
        )

    for file_name in unique_files:
        normalized = file_name.replace("\\", "/")

        if normalized in PROTECTED_PATHS:
            raise RuntimeError(
                f"Protected file cannot be modified: {normalized}"
            )

        if any(
            normalized.startswith(prefix)
            for prefix in PROTECTED_PREFIXES
        ):
            raise RuntimeError(
                f"Protected path cannot be modified: {normalized}"
            )

    diff = run_command(
        ["git", "diff", "--", *unique_files],
        check=False,
    )

    diff_text = diff.stdout

    changed_lines = [
        line
        for line in diff_text.splitlines()
        if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
    ]

    if len(changed_lines) > MAX_CHANGED_LINES:
        raise RuntimeError(
            f"Too many changed lines: "
            f"{len(changed_lines)} > {MAX_CHANGED_LINES}"
        )

    for pattern in SECRET_PATTERNS:
        if pattern.search(diff_text):
            raise RuntimeError(
                "Possible secret or credential detected in diff."
            )


def validate_improvement(files: list[str]) -> None:
    check_syntax(files)
    verify_security_and_limits(files)
    run_test_suite()


# ---------------------------------------------------------------------------
# Improvement helpers
# ---------------------------------------------------------------------------

def read_file(path: Path) -> str:
    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, content: str) -> bool:
    old = read_file(path)

    if old == content:
        return False

    path.write_text(content, encoding="utf-8")
    return True


def add_test_if_missing(
    tests_file: Path,
    test_name: str,
    test_body: str,
) -> bool:
    content = read_file(tests_file)

    if not content:
        return False

    if test_name in content:
        return False

    addition = (
        "\n\n"
        f"{test_body.rstrip()}\n"
    )

    return write_if_changed(
        tests_file,
        content.rstrip() + addition,
    )


# ---------------------------------------------------------------------------
# Improvement 1
# ---------------------------------------------------------------------------

def improvement_deprecation_warning() -> tuple[str, list[str]]:
    path = ROOT / "backend" / "ai" / "settings.py"
    content = read_file(path)

    target = '"()": "pythonjsonlogger.json.JsonFormatter"'

    if "pythonjsonlogger.json.JsonFormatter" in content:
        return "", []

    if "pythonjsonlogger.jsonlogger.JsonFormatter" not in content:
        return "", []

    new_content = content.replace(
        '"()": "pythonjsonlogger.jsonlogger.JsonFormatter"',
        target,
    )

    if new_content == content:
        return "", []

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Fix python-json-logger deprecated JsonFormatter import",
        ["backend/ai/settings.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 2
# ---------------------------------------------------------------------------

def improvement_health_timestamp() -> tuple[str, list[str]]:
    path = ROOT / "backend" / "todo" / "views.py"
    content = read_file(path)

    if not content:
        return "", []

    if '"timestamp":' in content:
        return "", []

    if '"status": "ok"' not in content:
        return "", []

    if "import datetime" not in content:
        content = "import datetime\n" + content

    marker = '"status": "ok",'

    replacement = (
        '"status": "ok",\n'
        '        "timestamp": '
        'datetime.datetime.now(datetime.timezone.utc).isoformat(),'
    )

    new_content = content.replace(
        marker,
        replacement,
        1,
    )

    if new_content == content:
        return "", []

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Add UTC timestamp to health endpoint",
        ["backend/todo/views.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 3
# ---------------------------------------------------------------------------

def improvement_security_headers() -> tuple[str, list[str]]:
    path = ROOT / "backend" / "ai" / "settings.py"
    content = read_file(path)

    if not content:
        return "", []

    if "SECURE_CONTENT_TYPE_NOSNIFF" in content:
        return "", []

    marker = 'DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"'

    if marker not in content:
        return "", []

    addition = (
        marker
        + "\n\n"
        + "# Browser security hardening\n"
        + "SECURE_CONTENT_TYPE_NOSNIFF = True\n"
        + "SECURE_BROWSER_XSS_FILTER = True\n"
    )

    new_content = content.replace(
        marker,
        addition,
        1,
    )

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Harden Django browser security headers",
        ["backend/ai/settings.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 4
# ---------------------------------------------------------------------------

def improvement_tool_edge_cases() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    if "test_calculator_division_by_zero" in read_file(path):
        return "", []

    content = read_file(path)

    imports = ""

    if "import pytest" not in content:
        imports += "import pytest\n"

    if "ToolExecutionError" not in content:
        imports += "from todo.tools import ToolExecutionError\n"

    if imports:
        content = imports + "\n" + content

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

    final_content = content.rstrip() + "\n\n" + addition.strip() + "\n"
    if not write_if_changed(path, final_content):
        return "", []

    return (
        "Add tool boundary tests for calculator and repository search",
        ["tests/test_tools.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 5
# ---------------------------------------------------------------------------

def improvement_repository_search_whitespace() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    test = """
def test_repository_search_whitespace_query():
    with pytest.raises(
        ToolExecutionError,
        match="Search query must be between 1 and 100 characters",
    ):
        execute_tool(
            "repository_search",
            {"query": "   "},
        )
"""

    if "test_repository_search_whitespace_query" in read_file(path):
        return "", []

    add_test_if_missing(
        path,
        "test_repository_search_whitespace_query",
        test,
    )

    return (
        "Add whitespace-only repository search validation test",
        ["tests/test_tools.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 6
# ---------------------------------------------------------------------------

def improvement_calculator_invalid_expression() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    test = """
def test_calculator_invalid_expression():
    with pytest.raises(ToolExecutionError):
        execute_tool(
            "calculator",
            {"expression": "this is not valid math"},
        )
"""

    if "test_calculator_invalid_expression" in read_file(path):
        return "", []

    add_test_if_missing(
        path,
        "test_calculator_invalid_expression",
        test,
    )

    return (
        "Add calculator invalid-expression regression test",
        ["tests/test_tools.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 7
# ---------------------------------------------------------------------------

def improvement_calculator_empty_expression() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    test = """
def test_calculator_empty_expression():
    with pytest.raises(ToolExecutionError):
        execute_tool(
            "calculator",
            {"expression": ""},
        )
"""

    if "test_calculator_empty_expression" in read_file(path):
        return "", []

    add_test_if_missing(
        path,
        "test_calculator_empty_expression",
        test,
    )

    return (
        "Add calculator empty-expression regression test",
        ["tests/test_tools.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 8
# ---------------------------------------------------------------------------

def improvement_tool_missing_expression() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    test = """
def test_calculator_missing_expression():
    with pytest.raises(ToolExecutionError):
        execute_tool(
            "calculator",
            {},
        )
"""

    if "test_calculator_missing_expression" in read_file(path):
        return "", []

    add_test_if_missing(
        path,
        "test_calculator_missing_expression",
        test,
    )

    return (
        "Add calculator missing-input regression test",
        ["tests/test_tools.py"],
    )


# ---------------------------------------------------------------------------
# Improvement 9
# ---------------------------------------------------------------------------

def improvement_health_endpoint_test() -> tuple[str, list[str]]:
    path = ROOT / "tests" / "test_tools.py"

    if not path.exists():
        return "", []

    # Only apply this if the project already has Django test infrastructure.
    if "django.test" not in read_file(path):
        return "", []

    return "", []


# ---------------------------------------------------------------------------
# Improvement 10
# ---------------------------------------------------------------------------

def improvement_python_cache_ignore() -> tuple[str, list[str]]:
    path = ROOT / ".gitignore"

    content = read_file(path)

    if not content:
        return "", []

    required = [
        "__pycache__/",
        "*.py[cod]",
    ]

    missing = [
        item
        for item in required
        if item not in content
    ]

    if not missing:
        return "", []

    new_content = content.rstrip() + "\n\n# Python cache\n"

    for item in missing:
        new_content += item + "\n"

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Improve Python cache exclusion in gitignore",
        [".gitignore"],
    )


# ---------------------------------------------------------------------------
# Improvement 11
# ---------------------------------------------------------------------------

def improvement_test_cache_ignore() -> tuple[str, list[str]]:
    path = ROOT / ".gitignore"

    content = read_file(path)

    if not content:
        return "", []

    if ".pytest_cache/" in content:
        return "", []

    new_content = (
        content.rstrip()
        + "\n\n# Pytest cache\n"
        + ".pytest_cache/\n"
    )

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Exclude pytest cache artifacts from repository",
        [".gitignore"],
    )


# ---------------------------------------------------------------------------
# Improvement 12
# ---------------------------------------------------------------------------

def improvement_django_cache_ignore() -> tuple[str, list[str]]:
    path = ROOT / ".gitignore"

    content = read_file(path)

    if not content:
        return "", []

    if ".mypy_cache/" in content:
        return "", []

    new_content = (
        content.rstrip()
        + "\n\n# Python tooling cache\n"
        + ".mypy_cache/\n"
    )

    if not write_if_changed(path, new_content):
        return "", []

    return (
        "Exclude Python tooling cache artifacts",
        [".gitignore"],
    )


# ---------------------------------------------------------------------------
# Improvement catalog
# ---------------------------------------------------------------------------

CATALOG_IMPROVEMENTS: list[Callable[[], tuple[str, list[str]]]] = [
    improvement_deprecation_warning,
    improvement_health_timestamp,
    improvement_security_headers,
    improvement_tool_edge_cases,
    improvement_repository_search_whitespace,
    improvement_calculator_invalid_expression,
    improvement_calculator_empty_expression,
    improvement_tool_missing_expression,
    improvement_health_endpoint_test,
    improvement_python_cache_ignore,
    improvement_test_cache_ignore,
    improvement_django_cache_ignore,
]


# ---------------------------------------------------------------------------
# Improvement selection
# ---------------------------------------------------------------------------

def get_logged_titles() -> set[str]:
    if not LOG_FILE.exists():
        return set()

    titles: set[str] = set()

    for line in LOG_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        if not line.startswith("|"):
            continue

        columns = [part.strip() for part in line.split("|")]

        if len(columns) >= 4:
            titles.add(columns[2])

    return titles


def execute_catalog_improvement() -> tuple[str, list[str]]:
    """
    Find the first improvement that has not already been verified.

    IMPORTANT:
    Improvement functions are only allowed to mutate the repository
    when they know the improvement is applicable.
    """
    logged_titles = get_logged_titles()

    for improvement_func in CATALOG_IMPROVEMENTS:
        before = run_command(
            ["git", "status", "--porcelain"],
            check=False,
        ).stdout

        title, files = improvement_func()

        if not title:
            after = run_command(
                ["git", "status", "--porcelain"],
                check=False,
            ).stdout
            if after != before:
                raise RuntimeError(
                    f"{improvement_func.__name__} modified the repository "
                    "without returning an improvement."
                )
            continue

        if title in logged_titles:
            for file_name in files:
                run_command(
                    ["git", "restore", "--", file_name],
                    check=False,
                )
            continue

        return title, files

    return "", []


# ---------------------------------------------------------------------------
# Improvement log
# ---------------------------------------------------------------------------

def update_log(
    title: str,
    target_files: list[str],
) -> None:
    LOG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    content = ""

    if LOG_FILE.exists():
        content = LOG_FILE.read_text(
            encoding="utf-8"
        )

    if content and not content.endswith("\n"):
        content += "\n"

    LOG_FILE.write_text(
        content + entry,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Jarvis Autonomous Daily Improvement Engine"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate an improvement without committing",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run validation without applying improvements",
    )

    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit locally but do not push",
    )

    args = parser.parse_args()

    print("==============================================")
    print(" Jarvis Autonomous Daily Improvement Engine")
    print("==============================================")

    # ------------------------------------------------------------------
    # Repository safety
    # ------------------------------------------------------------------

    if not repository_is_clean():
        print(
            "Repository is not clean. "
            "Refusing autonomous modification.",
            file=sys.stderr,
        )
        return 1

    baseline_commit = run_command(
        ["git", "rev-parse", "HEAD"]
    ).stdout.strip()

    branch = run_command(
        ["git", "branch", "--show-current"]
    ).stdout.strip()

    print(f"Branch: {branch}")
    print(f"Baseline commit: {baseline_commit}")

    if branch != "main":
        print(
            "Engine must operate directly on main.",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # Baseline validation
    # ------------------------------------------------------------------

    print("Running baseline validation...")

    try:
        run_test_suite()
    except Exception as exc:
        print(
            f"Baseline validation failed: {exc}",
            file=sys.stderr,
        )
        return 1

    print("Baseline validation passed.")

    if args.check_only:
        print("Check-only mode complete.")
        return 0

    # ------------------------------------------------------------------
    # Select improvement
    # ------------------------------------------------------------------

    title, target_files = execute_catalog_improvement()

    if not title:
        print()
        print("No unapplied safe improvement is currently available.")
        print("Repository remains unchanged.")
        print("Baseline validation passed.")
        return 0

    print()
    print(f"Selected improvement: {title}")
    print(f"Target files: {target_files}")

    # ------------------------------------------------------------------
    # Validate improvement
    # ------------------------------------------------------------------

    try:
        validate_improvement(target_files)

        print()
        print("Post-improvement validation PASSED.")

    except Exception as exc:
        print()
        print(
            f"Validation FAILED: {exc}",
            file=sys.stderr,
        )
        print("Initiating rollback...", file=sys.stderr)

        if not rollback_to_baseline(baseline_commit):
            return 2

        print("Improvement rejected safely.")
        return 0

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    if args.dry_run:
        print()
        print("Dry-run mode enabled.")
        print("Rolling back validated candidate...")

        if not rollback_to_baseline(baseline_commit):
            return 2

        print("Dry run completed successfully.")
        return 0

    # ------------------------------------------------------------------
    # Verify repository before commit
    # ------------------------------------------------------------------

    status = run_command(
        ["git", "status", "--porcelain"]
    ).stdout.strip()

    if not status:
        print(
            "Improvement produced no repository changes.",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # Record verified improvement
    # ------------------------------------------------------------------

    try:
        update_log(
            title,
            target_files,
        )

        log_file = str(LOG_FILE.relative_to(ROOT))
        final_files = list(dict.fromkeys([*target_files, log_file]))

        # Validate the complete change that is about to be committed,
        # including the generated improvement log entry.
        check_syntax([f for f in final_files if f.endswith(".py")])
        verify_security_and_limits(final_files)

        # Make sure only intended files are staged.
        run_command(["git", "add", "--", *final_files])

        staged = run_command(
            ["git", "diff", "--cached", "--name-only"],
            check=False,
        ).stdout.splitlines()

        if sorted(staged) != sorted(final_files):
            raise RuntimeError(
                "Unexpected files would be included in the commit: "
                + ", ".join(staged)
            )

    except Exception as exc:
        print(
            f"Final pre-commit validation failed: {exc}",
            file=sys.stderr,
        )
        if not rollback_to_baseline(baseline_commit):
            return 2
        return 1

    commit_message = (
        f"chore: daily improvement - {title} [skip ci]"
    )

    commit = run_command(
        ["git", "commit", "-m", commit_message],
        check=False,
    )

    if commit.returncode != 0:
        print(
            "Commit failed.",
            file=sys.stderr,
        )

        if not rollback_to_baseline(baseline_commit):
            return 2
        return 1

    print()
    print(f"Committed: {commit_message}")

    # ------------------------------------------------------------------
    # Push directly to main
    # ------------------------------------------------------------------

    if args.no_push:
        print("--no-push enabled. Commit retained locally.")
        return 0

    print("Pushing verified improvement directly to main...")

    push = run_command(
        ["git", "push", "origin", "main"],
        check=False,
    )

    if push.returncode != 0:
        print(
            "Push failed:",
            push.stderr.strip(),
            file=sys.stderr,
        )
        print(
            "The verified commit remains local to this runner and was NOT "
            "confirmed on origin/main.",
            file=sys.stderr,
        )
        return 1

    print("Push successful.")
    print("Daily improvement completed successfully.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
