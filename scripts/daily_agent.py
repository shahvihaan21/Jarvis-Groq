"""Bounded autonomous daily improvement agent for Jarvis.

The agent may apply one model-proposed project change, validate it, and commit
it on main. It never reads or writes credentials, workflows, deployment files,
or other protected paths, and it never executes model-supplied commands.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / ".github" / "codex" / "daily-improvement.md"
MAX_FILE_BYTES = 48 * 1024
MAX_CONTEXT_BYTES = 24 * 1024
MAX_CHANGED_FILES = 5
MAX_CHANGED_LINES = 200
REQUEST_TIMEOUT_SECONDS = 120
COMMAND_TIMEOUT_SECONDS = 300
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
}
TEXT_FILENAMES = {".gitignore", "Procfile", "runtime.txt"}
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "credentials",
    "dist",
    "env",
    "node_modules",
    "secrets",
    "venv",
}
PROTECTED_FILE_NAMES = {"vercel.json", "Procfile", "runtime.txt", "daily_agent.py"}


def is_sensitive_or_unnecessary(path: Path) -> bool:
    """Exclude credentials, environments, caches, and other sensitive paths."""

    for part in path.relative_to(ROOT).parts:
        lowered = part.lower()
        if lowered in EXCLUDED_DIRECTORY_NAMES or lowered.startswith(".env"):
            return True
        if any(token in lowered for token in ("secret", "credential", "private", "api_key", "apikey")):
            return True
    return False


def repository_tree() -> list[str]:
    paths: list[str] = []
    for current, directories, files in os.walk(ROOT, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            directory
            for directory in directories
            if not is_sensitive_or_unnecessary(current_path / directory)
            and not (current_path / directory).is_symlink()
        )
        for filename in sorted(files):
            path = current_path / filename
            if not path.is_symlink() and not is_sensitive_or_unnecessary(path):
                paths.append(path.relative_to(ROOT).as_posix())
    return paths


def is_relevant_text_file(path: Path) -> bool:
    return path.name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def redact_sensitive_content(content: str) -> str:
    """Redact common credentials before content is placed in the prompt."""

    content = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", content)
    content = re.sub(r"\b[A-Za-z0-9]{2,12}_[A-Za-z0-9_-]{20,}\b", "[REDACTED_API_KEY]", content)
    return re.sub(
        r"(?im)((?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\s*[:=]\s*)([\"']?)[^\s\"']+\2",
        r"\1[REDACTED]",
        content,
    )


def load_rules() -> str:
    if not RULES_PATH.is_file() or is_sensitive_or_unnecessary(RULES_PATH):
        raise RuntimeError("canonical agent rules file was not found")
    try:
        if RULES_PATH.stat().st_size > MAX_FILE_BYTES:
            raise RuntimeError("agent rules file exceeds the size limit")
        return RULES_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise RuntimeError("could not read the canonical agent rules file") from error


def read_relevant_files(tree: list[str]) -> str:
    sections: list[str] = []
    total_bytes = 0
    agent_path = Path(__file__).resolve()
    for relative_name in tree:
        path = ROOT / relative_name
        if path.resolve() == agent_path or not is_relevant_text_file(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            content = redact_sensitive_content(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue

        section = f"\n--- {relative_name} ---\n{content}"
        section_bytes = len(section.encode("utf-8"))
        if total_bytes + section_bytes > MAX_CONTEXT_BYTES:
            break
        sections.append(section)
        total_bytes += section_bytes
    return "".join(sections)


def build_prompts() -> tuple[str, str]:
    rules = load_rules()
    tree = repository_tree()
    file_contents = read_relevant_files(tree)
    system_prompt = """You are a careful autonomous maintenance engineer for Jarvis.
Operate on the current main branch and follow the repository rules exactly.
Select EXACTLY ONE small, worthwhile, low-risk improvement, or report that no
worthwhile improvement exists. Do not modify workflows, deployment files,
credentials, secrets, or unrelated files. Do not propose shell commands.

Return ONLY ONE valid JSON object with exactly these fields. Do not use Markdown
fences. Do not include explanation, commentary, or any text before or after the
JSON object:
{
  "no_improvement": false,
  "improvement": "short description",
  "why": "why it matters",
  "files": ["repo/relative/path.py"],
  "implementation": "what the change does",
  "tests": ["test/check that should be run"],
  "patch": "one unified diff"
}

For no improvement, set no_improvement to true, set patch to an empty string,
and explain why in the why field. The patch must implement only the selected
improvement and must not include workflow, deployment, secret, or credential
changes.
"""
    user_prompt = f"""Review this bounded repository summary and implement one improvement through a unified diff.
Your entire response must be exactly one valid JSON object matching the schema
in the system instructions: no Markdown fences, explanation, or surrounding text.

Repository file tree (sensitive and excluded paths omitted):
{chr(10).join(tree)}

Relevant text/source files (size-limited and credential-redacted):
{file_contents}

Canonical agent rules:
{rules}
"""
    return system_prompt, user_prompt


def request_proposal(system_prompt: str, user_prompt: str) -> dict[str, object]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")
    model = os.environ.get("OPENROUTER_MODEL")
    if not model:
        raise RuntimeError("OPENROUTER_MODEL is not set in the environment")

    payload_dict: dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 1000,
    }

    def send_api_request(payload: dict[str, object]) -> bytes:
        request_body = json.dumps(payload).encode("utf-8")
        request = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()

    try:
        response_body = send_api_request(payload_dict)
    except HTTPError as error:
        err_bytes = error.read()
        summary = api_error_summary(err_bytes)

        if error.code == 402 or "can only afford" in summary.lower() or "max_tokens" in summary.lower():
            match = re.search(r"can only afford (\d+)", summary)
            affordable = int(match.group(1)) if match else 800
            payload_dict["max_tokens"] = min(affordable, 1000)

        if "response_format" in payload_dict:
            payload_dict.pop("response_format", None)

        try:
            response_body = send_api_request(payload_dict)
        except Exception as retry_error:
            raise RuntimeError(
                f"OpenRouter API returned HTTP {error.code}: {summary}"
            ) from retry_error
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError("OpenRouter API request could not be completed") from error

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"OpenRouter response body was not valid JSON (line {error.lineno}, column {error.colno})"
        ) from error

    if not isinstance(result, dict):
        raise RuntimeError("OpenRouter response envelope was not a JSON object")
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter response had no valid choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter response had no valid assistant message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenRouter assistant message content was empty or not text")
    return parse_proposal(content)


def api_error_summary(response_body: bytes) -> str:
    """Return a short, credential-safe summary of an API error response."""

    try:
        payload = json.loads(response_body)
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(error, dict):
            message = error.get("message") or error.get("type") or error.get("code")
            if isinstance(message, str) and message.strip():
                detail = redact_sensitive_content(message.strip())[:240]
                if any(marker in detail.lower() for marker in ("response_format", "json_object", "structured output")):
                    return f"structured JSON output was rejected: {detail}"
                return detail
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        pass
    return "no safe error detail returned"


def parse_proposal(content: str) -> dict[str, object]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    try:
        proposal = json.loads(content)
    except json.JSONDecodeError:
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx > start_idx:
            try:
                proposal = json.loads(content[start_idx : end_idx + 1])
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"OpenRouter assistant content was not valid JSON (line {error.lineno}, column {error.colno})"
                ) from error
        else:
            raise RuntimeError("OpenRouter assistant content was not valid JSON")

    if not isinstance(proposal, dict):
        raise RuntimeError("OpenRouter assistant content was not a JSON object")
    required_fields = {
        "no_improvement",
        "improvement",
        "why",
        "files",
        "implementation",
        "tests",
        "patch",
    }
    missing_fields = sorted(required_fields - proposal.keys())
    if missing_fields:
        raise RuntimeError(f"OpenRouter proposal is missing required fields: {', '.join(missing_fields)}")
    if not isinstance(proposal["no_improvement"], bool):
        raise RuntimeError("OpenRouter proposal has an invalid no_improvement field")
    for field in ("improvement", "why", "implementation", "patch"):
        if not isinstance(proposal[field], str):
            raise RuntimeError(f"OpenRouter proposal has an invalid {field} field")
    for field in ("files", "tests"):
        if not isinstance(proposal[field], list) or not all(isinstance(item, str) for item in proposal[field]):
            raise RuntimeError(f"OpenRouter proposal has an invalid {field} field")
    if proposal["no_improvement"] is False:
        if not proposal["improvement"].strip():
            raise RuntimeError("OpenRouter proposal is missing an improvement description")
        if not proposal["patch"].strip():
            raise RuntimeError("OpenRouter proposal is missing a patch")
    elif proposal["patch"].strip():
        raise RuntimeError("OpenRouter no-improvement proposal unexpectedly included a patch")
    return proposal


def run_command(arguments: list[str], *, input_text: str | None = None) -> str:
    """Run a fixed, non-shell development/Git command without displaying output."""

    try:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL if input_text is None else None,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"command failed to complete: {arguments[0]}") from error
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit status {result.returncode}: {arguments[0]}")
    return result.stdout


def git_status_entries() -> list[str]:
    output = run_command(["git", "status", "--porcelain=v1", "-z"])
    return [entry[3:] for entry in output.split("\0") if entry]


def changed_paths() -> list[str]:
    tracked = run_command(["git", "diff", "--name-only"]).splitlines()
    untracked = [path for path in git_status_entries() if path]
    return sorted(set(path.replace("\\", "/") for path in tracked + untracked))


def protected_change(path_name: str) -> bool:
    path = Path(path_name)
    if path.is_absolute() or ".." in path.parts:
        return True
    lowered = path_name.lower()
    if path.name in PROTECTED_FILE_NAMES:
        return True
    if lowered == ".git" or lowered.startswith(".git/"):
        return True
    if lowered == ".github" or lowered.startswith(".github/"):
        return True
    if lowered == "scripts/daily_agent.py" or path.name == "daily_agent.py":
        return True
    return is_sensitive_or_unnecessary(ROOT / path_name)


def validate_changed_paths(paths: list[str]) -> None:
    if not paths:
        raise RuntimeError("the proposed patch changed no files")
    if len(paths) > MAX_CHANGED_FILES:
        raise RuntimeError("the proposed improvement exceeds the five-file limit")
    if any(protected_change(path) for path in paths):
        raise RuntimeError("the proposed patch touches a protected file or path")
    for path_name in paths:
        path = ROOT / path_name
        if path.exists() and path.is_symlink():
            raise RuntimeError("the proposed patch creates or modifies a symlink")


def staged_change_limits(paths: list[str]) -> None:
    output = run_command(["git", "diff", "--cached", "--numstat", "--"]).splitlines()
    changed_lines = 0
    staged_paths: list[str] = []
    for line in output:
        additions, deletions, path_name = line.split("\t", 2)
        staged_paths.append(path_name.replace("\\", "/"))
        if additions != "-" and deletions != "-":
            changed_lines += int(additions) + int(deletions)
    if sorted(set(staged_paths)) != sorted(set(paths)):
        raise RuntimeError("staged files did not match the proposed change")
    if changed_lines > MAX_CHANGED_LINES:
        raise RuntimeError("the proposed improvement exceeds the 200-line limit")


def final_diff_is_safe() -> None:
    diff = run_command(["git", "diff", "--cached", "--no-ext-diff", "--"])
    if re.search(r"sk-or-v1-[A-Za-z0-9_-]+", diff) or re.search(
        r"\b[A-Za-z0-9]{2,12}_[A-Za-z0-9_-]{20,}\b", diff
    ) or re.search(
        r"(?im)(?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\s*[:=]\s*[^$\s{][^\s]*", diff
    ):
        raise RuntimeError("the staged diff appears to contain a credential")


def inspect_staged_changes() -> None:
    """Print the final status and diff summary before the commit decision."""

    print("Final git status:")
    print(run_command(["git", "status", "--short"]).rstrip())
    print("Final staged diff check:")
    run_command(["git", "diff", "--cached", "--check"])
    print("Final staged diff:")
    print(run_command(["git", "diff", "--cached", "--no-ext-diff", "--"]).rstrip())


def rollback(paths: list[str]) -> None:
    """Restore only this run's bounded changes after a failed validation."""

    if paths:
        subprocess.run(
            ["git", "restore", "--source=HEAD", "--worktree", "--staged", "--", *paths],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    tracked_paths = set(run_command(["git", "ls-files", "--"]).splitlines())
    for path_name in paths:
        path = ROOT / path_name
        if path.is_file() and path_name not in tracked_paths:
            path.unlink()


def run_validation(paths: list[str]) -> None:
    python_paths = [path for path in paths if path.lower().endswith(".py")]
    if python_paths:
        script = (
            "import ast, pathlib, sys; "
            "[ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in sys.argv[1:]]"
        )
        run_command([sys.executable, "-c", script, *python_paths])
    try:
        run_command([sys.executable, "-c", "import pytest"])
    except RuntimeError:
        return
    run_command([sys.executable, "-m", "pytest", "-q"])


def commit_and_push(description: str, paths: list[str]) -> None:
    safe_description = re.sub(r"[^A-Za-z0-9 ._-]", "", description).strip()
    safe_description = " ".join(safe_description.split())[:80].strip()
    if not safe_description:
        safe_description = "small maintenance improvement"
    run_command(["git", "commit", "-m", f"chore: daily improvement - {safe_description}"])
    run_command(["git", "push", "origin", "main"])


def main() -> int:
    paths: list[str] = []
    improvement = ""
    try:
        if run_command(["git", "branch", "--show-current"]).strip() != "main":
            raise RuntimeError("agent must run on main")
        if git_status_entries():
            raise RuntimeError("working tree is not clean")
        system_prompt, user_prompt = build_prompts()
        proposal = request_proposal(system_prompt, user_prompt)
        if proposal.get("no_improvement") is True:
            reason = redact_sensitive_content(str(proposal.get("why", "No worthwhile improvement exists.")))
            print("No worthwhile improvement exists.")
            print(f"Reason: {reason}")
            return 0

        improvement = str(proposal.get("improvement", "")).strip()
        patch = proposal.get("patch")
        if not improvement or not isinstance(patch, str) or not patch.strip():
            raise RuntimeError("proposal did not contain one improvement and a patch")
        run_command(["git", "apply", "--check", "--whitespace=nowarn", "-"], input_text=patch)
        run_command(["git", "apply", "--whitespace=nowarn", "-"], input_text=patch)
        paths = changed_paths()
        validate_changed_paths(paths)
        run_command(["git", "add", "--", *paths])
        staged_change_limits(paths)
        final_diff_is_safe()
        inspect_staged_changes()
        run_validation(paths)
        commit_and_push(improvement, paths)
    except RuntimeError as error:
        if paths:
            rollback(paths)
        print(f"Daily agent stopped: {redact_sensitive_content(str(error))}", file=sys.stderr)
        return 1

    print(f"Implemented and pushed one improvement: {redact_sensitive_content(improvement)}")
    print(f"Files changed: {', '.join(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
