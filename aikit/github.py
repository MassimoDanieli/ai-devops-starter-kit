"""Minimal GitHub REST helpers (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def _request(method: str, url: str, token: str, payload: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def upsert_pr_comment(repo: str, pr: int, body: str, marker: str, token: str | None = None) -> str:
    """Create or update the single comment on a PR that starts with ``marker``.

    Re-running a workflow edits the same comment instead of piling up new ones.
    Returns "created" or "updated".
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    full = f"{marker}\n{body}"
    comments = _request("GET", f"{API}/repos/{repo}/issues/{pr}/comments?per_page=100", token)
    for c in comments or []:
        if isinstance(c, dict) and str(c.get("body", "")).startswith(marker):
            _request("PATCH", f"{API}/repos/{repo}/issues/comments/{c['id']}", token, {"body": full})
            return "updated"
    _request("POST", f"{API}/repos/{repo}/issues/{pr}/comments", token, {"body": full})
    return "created"
