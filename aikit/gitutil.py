"""Small git helpers. Everything goes through ``git`` on PATH."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(*args: str, cwd: str | Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def diff(base: str, head: str = "HEAD", cwd: str | Path | None = None, context: int = 5) -> str:
    """Unified diff of what ``head`` adds on top of ``base`` (merge-base aware)."""
    return git("diff", f"-U{context}", f"{base}...{head}", cwd=cwd)


def changed_files(base: str, head: str = "HEAD", cwd: str | Path | None = None) -> list[str]:
    out = git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}", cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def recently_changed_files(days: int, cwd: str | Path | None = None) -> set[str]:
    out = git("log", f"--since={days} days ago", "--name-only", "--pretty=format:", cwd=cwd)
    return {line for line in out.splitlines() if line.strip()}


def last_tag(ref: str = "HEAD", cwd: str | Path | None = None) -> str | None:
    try:
        return git("describe", "--tags", "--abbrev=0", ref, cwd=cwd).strip() or None
    except GitError:
        return None


def tag_at_head(cwd: str | Path | None = None) -> str | None:
    """Tag pointing exactly at HEAD, if any (e.g. when a workflow runs on a tag push)."""
    try:
        return git("describe", "--tags", "--exact-match", "HEAD", cwd=cwd).strip() or None
    except GitError:
        return None


def changelog_range(cwd: str | Path | None = None) -> tuple[str | None, str | None]:
    """(since_ref, version) for the next changelog entry.

    On a tagged commit: commits since the previous tag, version = that tag.
    Otherwise: commits since the last tag, version unknown (caller decides).
    """
    here = tag_at_head(cwd)
    if here:
        try:
            git("rev-parse", "HEAD^", cwd=cwd)
        except GitError:
            return None, here
        return last_tag("HEAD^", cwd=cwd), here
    return last_tag(cwd=cwd), None


@dataclass
class Commit:
    sha: str
    subject: str
    body: str
    author: str


_SEP = "\x1f"
_END = "\x1e"


def commits_since(ref: str | None, cwd: str | Path | None = None, limit: int = 200) -> list[Commit]:
    rng = f"{ref}..HEAD" if ref else "HEAD"
    fmt = _SEP.join(["%h", "%s", "%b", "%an"]) + _END
    out = git("log", f"-n{limit}", "--no-merges", f"--pretty=format:{fmt}", rng, cwd=cwd)
    commits = []
    for record in out.split(_END):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body, author = (record.split(_SEP) + ["", "", "", ""])[:4]
        commits.append(Commit(sha.strip(), subject.strip(), body.strip(), author.strip()))
    return commits


def read_snippet(path: str | Path, line: int, radius: int = 15) -> str:
    """Numbered lines around ``line`` (1-based); empty string if unreadable."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return "\n".join(f"{n:>5} | {lines[n - 1]}" for n in range(start, end + 1))
