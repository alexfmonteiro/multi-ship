"""Spec/issue resolver for multi-ship.

Public entry point:
    resolve_specs(tokens, issue_numbers, cfg, repo) -> list[str]

Returns ordered, repo-relative path strings. Raises ResolveError on any
unresolvable reference before starting a run.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List

from .config import Config


class ResolveError(Exception):
    """Raised when a spec reference cannot be resolved to an existing file."""


# ---------------------------------------------------------------------------
# GitHub seam (mockable for tests)
# ---------------------------------------------------------------------------

def _gh_issue_title(num: int) -> str:
    """Return the title of a GitHub issue by number.

    Shells: gh issue view <num> --json title -q .title
    Raises subprocess.CalledProcessError or FileNotFoundError on failure.
    """
    result = subprocess.run(
        ["gh", "issue", "view", str(num), "--json", "title", "-q", ".title"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _gh_issue_body(num: int) -> str:
    """Return the body of a GitHub issue by number.

    Shells: gh issue view <num> --json body -q .body
    Raises subprocess.CalledProcessError or FileNotFoundError on failure.
    """
    result = subprocess.run(
        ["gh", "issue", "view", str(num), "--json", "body", "-q", ".body"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spec_dir_from_glob(spec_glob: str) -> str:
    """Derive the spec directory from cfg.spec_glob.

    Returns a posix-style string: 'docs/specs' or '.' (never empty, never '/').
    Raises ResolveError if spec_glob contains '**'.
    """
    if "**" in spec_glob:
        raise ResolveError(
            f"recursive glob '**' in spec_glob '{spec_glob}' is not supported — "
            "multi-ship cannot derive a unique spec directory from a recursive pattern"
        )
    parent = str(Path(spec_glob).parent)
    # Path('.').parent is '.' on all platforms
    return parent


def _resolve_issue(num: int, spec_dir: str, repo: Path) -> str:
    """Resolve a GitHub issue number to a repo-relative spec path.

    Strategy:
    1. Read issue title; if bracketed id prefix '[id]' present -> spec_dir/id.md
    2. Else read body and scan for first .md path under spec_dir
    3. If neither yields an existing file -> ResolveError

    Returns a repo-relative string.
    """
    try:
        title = _gh_issue_title(num)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ResolveError(
            f"could not resolve issue #{num} (gh not available or unauthenticated)"
        ) from exc

    # Strategy 1: bracketed id prefix in title
    m = re.match(r"^\[([^\]]+)\]", title)
    if m:
        issue_id = m.group(1)
        if spec_dir == ".":
            cand = f"{issue_id}.md"
        else:
            cand = f"{spec_dir}/{issue_id}.md"
        if (repo / cand).exists():
            return cand

    # Strategy 2: scan body for first .md path under spec_dir
    try:
        body = _gh_issue_body(num)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ResolveError(
            f"could not resolve issue #{num} (gh not available or unauthenticated)"
        ) from exc

    if spec_dir == ".":
        # Match a bare filename.md (no leading path)
        pattern = r"([\w\-./]+\.md)"
    else:
        escaped = re.escape(spec_dir)
        pattern = rf"({escaped}/[\w\-./]+\.md)"
    body_match = re.search(pattern, body)
    if body_match:
        cand = body_match.group(1)
        if (repo / cand).exists():
            return cand

    raise ResolveError(
        f"could not resolve issue #{num} to an existing spec file "
        f"(neither title prefix nor body contained a known path under '{spec_dir}')"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_GLOB_CHARS = set("*?[")


def resolve_specs(
    tokens: List[str],
    issue_numbers: List[int],
    cfg: Config,
    repo: Path,
) -> List[str]:
    """Resolve a list of tokens (and --issue integers) to repo-relative spec paths.

    Resolution order per positional token:
    1. GLOB — contains * ? [ (but ** is rejected)
    2. EXISTING PATH — (repo / token).exists()
    3. ISSUE REFERENCE — matches ^#\\d+$
    4. BARE ID — no '/', does not end in '.md'

    Tokens with '/' that are not existing paths and not globs are treated as
    explicit path references that must exist (falls through to existence check).

    All issue_numbers (--issue values) are appended after all positional tokens.

    Returns repo-relative strings. Raises ResolveError on first unresolvable
    reference before any run starts.
    """
    repo = Path(repo)
    spec_dir = _spec_dir_from_glob(cfg.spec_glob)

    results: List[str] = []

    for token in tokens:
        _resolve_token(token, spec_dir, repo, results)

    for num in (issue_numbers or []):
        path = _resolve_issue(num, spec_dir, repo)
        results.append(path)

    # Existence gate — validate every produced path before returning
    for path in results:
        if not (repo / path).exists():
            raise ResolveError(
                f"resolved path '{path}' does not exist in repo '{repo}'"
            )

    return results


def _resolve_token(token: str, spec_dir: str, repo: Path, results: List[str]) -> None:
    """Resolve a single token and extend `results` in-place."""

    # --- GLOB ---
    if any(c in token for c in _GLOB_CHARS):
        if "**" in token:
            raise ResolveError(
                f"recursive glob '**' in token '{token}' is not supported"
            )
        # Python 3.9-safe: Path(repo).glob(token) + .relative_to(repo)
        matches = sorted(
            str(p.relative_to(repo))
            for p in Path(repo).glob(token)
        )
        results.extend(matches)
        return

    # --- EXISTING PATH ---
    if (repo / token).exists():
        results.append(token)
        return

    # --- ISSUE REFERENCE: ^#\d+$ ---
    if re.match(r"^#\d+$", token):
        num = int(token[1:])
        # We call _resolve_issue but defer the existence gate to the post-loop check.
        # However _resolve_issue already checks existence, so this is fine.
        path = _resolve_issue(num, spec_dir, repo)
        results.append(path)
        return

    # --- BARE ID: no '/', does not end in '.md' ---
    if "/" not in token and not token.endswith(".md"):
        if spec_dir == ".":
            results.append(f"{token}.md")
        else:
            results.append(f"{spec_dir}/{token}.md")
        return

    # --- Anything else: explicit path that does not exist -> error ---
    # (path with slash not in repo, or .md file not in repo)
    raise ResolveError(
        f"spec '{token}' does not exist in repo '{repo}'"
    )
