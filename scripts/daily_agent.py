"""Read-only repository analysis agent for Jarvis."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
RULES_PATHS = (ROOT / ".github" / "codex" / "daily-improvement.md",)
MAX_FILE_BYTES = 48 * 1024
MAX_CONTEXT_BYTES = 180 * 1024
REQUEST_TIMEOUT_SECONDS = 60

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


def is_sensitive_or_unnecessary(path: Path) -> bool:
    """Keep sensitive files out of both the tree and the file-content scan."""

    relative_parts = path.relative_to(ROOT).parts
    for part in relative_parts:
        lowered = part.lower()
        if lowered in EXCLUDED_DIRECTORY_NAMES:
            return True
        if lowered.startswith(".env"):
            return True
        if any(token in lowered for token in ("secret", "credential", "private_key", "api_key")):
            return True
    return False


def repository_tree() -> list[str]:
    """Return repository file names without reading excluded files."""

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
    """Redact recognizable credentials before content can enter the prompt."""

    content = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", content)
    return re.sub(
        r"(?im)(OPENROUTER_API_KEY|SECRET_KEY)\s*([:=])\s*([\"']?)[^\s\"']+\3",
        r"\1\2 [REDACTED]",
        content,
    )


def load_rules() -> tuple[str, str]:
    for path in RULES_PATHS:
        if not path.is_file() or is_sensitive_or_unnecessary(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise RuntimeError("agent rules file exceeds the size limit")
            return path.read_text(encoding="utf-8", errors="replace"), path.relative_to(ROOT).as_posix()
        except OSError as error:
            raise RuntimeError("could not read the agent rules file") from error
    raise RuntimeError("agent rules file was not found")


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
    rules, rules_name = load_rules()
    tree = repository_tree()
    file_contents = read_relevant_files(tree)
    system_prompt = """You are a careful, read-only maintenance reviewer for Jarvis.
Follow the repository rules supplied by the user. Identify EXACTLY ONE small,
worthwhile, low-risk improvement, or explicitly report that no worthwhile
improvement exists. Do not propose code, patches, diffs, shell commands, or
file-writing instructions. Return exactly these headings:

Proposed improvement:
Why it matters:
Files likely involved:
Implementation approach:
Tests that should be run:
"""
    user_prompt = f"""Review this bounded repository summary.

Repository file tree (excluded and sensitive paths are omitted):
{chr(10).join(tree)}

Relevant text and source files (size-limited and credential-redacted):
{file_contents}

Agent rules loaded from {rules_name}:
{rules}
"""
    return system_prompt, user_prompt


def ask_openrouter(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")
    model = os.environ.get("OPENROUTER_MODEL")
    if not model:
        raise RuntimeError("OPENROUTER_MODEL is not set in the environment")

    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }
    ).encode("utf-8")
    request = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"OpenRouter API request failed with HTTP status {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError("OpenRouter API request could not be completed") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("OpenRouter API returned invalid JSON") from error

    try:
        proposal = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("OpenRouter API returned an unexpected response") from error
    if not isinstance(proposal, str) or not proposal.strip():
        raise RuntimeError("OpenRouter API returned an empty proposal")
    return proposal.strip()


def main() -> int:
    try:
        system_prompt, user_prompt = build_prompts()
        proposal = ask_openrouter(system_prompt, user_prompt)
    except RuntimeError as error:
        print(f"Daily agent failed: {error}", file=sys.stderr)
        return 1

    print("Daily improvement proposal")
    print(proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
