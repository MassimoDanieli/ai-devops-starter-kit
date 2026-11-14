"""Changelog from git history, in Keep a Changelog format.

The 2025 version summarised the last 10 commit subjects and appended
"## New release" at the bottom of the file. This one takes every commit since
the last tag (subject + body), groups them into sections, and inserts the new
entry at the top under the version you give it.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from .client import AIClient, strict_object
from .gitutil import Commit

SECTIONS = ["Added", "Changed", "Fixed", "Removed", "Security"]

SCHEMA = strict_object(
    {
        "highlights": {"type": "string", "description": "One sentence for users; empty if nothing notable."},
        **{
            s.lower(): {"type": "array", "items": {"type": "string"}, "description": f"'{s}' entries, user-facing wording."}
            for s in SECTIONS
        },
    }
)

SYSTEM = """You write release notes for end users and operators.
Group the commits into Added / Changed / Fixed / Removed / Security.
Merge commits that describe the same change into one entry. Skip pure
chores (formatting, CI tweaks, typo fixes) unless they affect users.
Each entry is one short line in plain language; mention the short sha
in parentheses at the end. Never invent changes that are not in the commits.
Write in {language}."""

HEADER = "# Changelog\n\nAll notable changes to this project are documented here.\n"


def build_prompt(commits: list[Commit]) -> str:
    rows = []
    for c in commits:
        body = f"\n    {c.body.replace(chr(10), chr(10) + '    ')}" if c.body else ""
        rows.append(f"- {c.sha} {c.subject}{body}")
    return "Commits (newest first):\n" + "\n".join(rows)


def summarise(client: AIClient, commits: list[Commit], language: str = "English") -> dict[str, Any]:
    if not commits:
        return {"highlights": "", **{s.lower(): [] for s in SECTIONS}}
    return client.complete(SYSTEM.format(language=language), build_prompt(commits), schema=SCHEMA, schema_name="changelog")


def render_entry(result: dict[str, Any], version: str, date: dt.date | None = None) -> str:
    date = date or dt.datetime.now(dt.timezone.utc).date()
    lines = [f"## [{version}] - {date.isoformat()}", ""]
    if result.get("highlights", "").strip():
        lines += [result["highlights"].strip(), ""]
    empty = True
    for s in SECTIONS:
        items = [i.strip() for i in result.get(s.lower(), []) if i.strip()]
        if items:
            empty = False
            lines += [f"### {s}", *[f"- {i}" for i in items], ""]
    if empty:
        lines += ["_No user-facing changes._", ""]
    return "\n".join(lines)


_FIRST_ENTRY = re.compile(r"^## ", re.MULTILINE)


def insert_entry(path: str | Path, entry: str) -> None:
    """Insert ``entry`` above the newest existing entry (or create the file)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8") if p.exists() else HEADER
    m = _FIRST_ENTRY.search(text)
    if m:
        new = text[: m.start()] + entry.rstrip() + "\n\n" + text[m.start() :]
    else:
        new = text.rstrip() + "\n\n" + entry.rstrip() + "\n"
    p.write_text(new, encoding="utf-8")
