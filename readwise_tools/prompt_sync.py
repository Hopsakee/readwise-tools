"""rw-prompt — fetch a prompt from the prompts-sync-library (and refresh it).

The prompts live in the locally-cloned `promptslibrarysync` repo under
`prompts-latest/`. "Get the latest" == `git pull` that clone, then read the
named file with its YAML frontmatter stripped (the body is the actual prompt).

This is the single source of prompts for rw-rate and rw-tag; both import
`load_prompt` so there is one read+refresh code path, not three.

Read-only on the repo: it pulls and reads, it never commits or pushes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastcore.script import call_parse

DEFAULT_REPO = Path.home() / "Code" / "promptslibrarysync"
PROMPTS_SUBDIR = "prompts-latest"


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block (content between the first two
    `---` delimiter lines). No frontmatter -> text returned unchanged."""
    lines = text.split("\n")
    first = second = -1
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if first == -1:
                first = i
            else:
                second = i
                break
    if first != -1 and second != -1:
        lines = lines[:first] + lines[second + 1 :]
    return "\n".join(lines).strip()


def _git_pull(repo: Path) -> None:
    """Quietly `git pull` the clone. A pull failure (offline) is non-fatal —
    we fall back to whatever the local clone already has."""
    try:
        subprocess.run(
            ["git", "-C", str(repo), "pull", "--quiet", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass  # offline / transient — read the cached copy


def load_prompt(name: str, repo: Path | str | None = None, pull: bool = True) -> str:
    """Return the frontmatter-stripped body of prompts-latest/<name>.md.

    `name` may be given with or without the .md suffix. Raises FileNotFoundError
    if the prompt does not exist after the (optional) pull.
    """
    repo_path = Path(repo).expanduser() if repo else DEFAULT_REPO
    if pull:
        _git_pull(repo_path)
    fname = name if name.endswith(".md") else f"{name}.md"
    prompt_path = repo_path / PROMPTS_SUBDIR / fname
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt not found: {prompt_path}")
    return strip_frontmatter(prompt_path.read_text(encoding="utf-8"))


@call_parse
def main(
    name: str,             # prompt file name in prompts-latest/ (with or without .md)
    repo: str = "",        # override the promptslibrarysync clone path
    no_pull: bool = False, # skip the git pull (offline / deterministic test)
):
    "Print a prompt from the prompts-sync-library, frontmatter stripped."
    try:
        body = load_prompt(name, repo=repo or None, pull=not no_pull)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    print(body)
