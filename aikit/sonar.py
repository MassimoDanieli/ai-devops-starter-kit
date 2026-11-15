"""SonarQube triage (successor of ai-code-quality-notifier).

Keeps the original idea — only BLOCKER/CRITICAL issues, only in files that were
touched recently — and adds what was missing: the real git history instead of
a mocked file list, the code around each issue, and a concrete fix proposed by
the model. Output is a PR comment instead of an email.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .client import AIClient, strict_object
from .gitutil import read_snippet

DEFAULT_SEVERITIES = ("BLOCKER", "CRITICAL")
DEFAULT_TYPES = ("CODE_SMELL", "BUG", "VULNERABILITY")
MAX_ISSUES = 25


def load_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fetch_report(host: str, project: str, token: str, branch: str | None = None) -> dict[str, Any]:
    """Fetch open issues from the SonarQube Web API (api/issues/search)."""
    params = {
        "componentKeys": project,
        "resolved": "false",
        "severities": ",".join(DEFAULT_SEVERITIES),
        "ps": "500",
    }
    if branch:
        params["branch"] = branch
    url = host.rstrip("/") + "/api/issues/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{token}:".encode()).decode())
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def component_path(issue: dict[str, Any]) -> str:
    comp = issue.get("component", "")
    return comp.split(":", 1)[1] if ":" in comp else comp


def select_issues(
    report: dict[str, Any],
    recent_files: set[str] | None,
    severities: tuple[str, ...] = DEFAULT_SEVERITIES,
    types: tuple[str, ...] = DEFAULT_TYPES,
) -> list[dict[str, Any]]:
    """Severe issues, optionally restricted to recently changed files."""
    out = []
    for issue in report.get("issues", []):
        if issue.get("severity") not in severities or issue.get("type") not in types:
            continue
        if recent_files is not None and component_path(issue) not in recent_files:
            continue
        out.append(issue)
    order = {s: i for i, s in enumerate(severities)}
    out.sort(key=lambda i: (order.get(i.get("severity"), 99), component_path(i), i.get("line", 0)))
    return out[:MAX_ISSUES]


SCHEMA = strict_object(
    {
        "overview": {"type": "string"},
        "items": {
            "type": "array",
            "items": strict_object(
                {
                    "key": {"type": "string", "description": "Sonar issue key, copied verbatim."},
                    "why_it_matters": {"type": "string"},
                    "fix": {"type": "string", "description": "Concrete patch or replacement code."},
                    "effort": {"type": "string", "enum": ["trivial", "small", "medium", "large"]},
                    "false_positive_likely": {"type": "boolean"},
                }
            ),
        },
    }
)

SYSTEM = """You help a team clear SonarQube findings quickly.
For each issue you get the rule, message and the code around the line.
Explain in one or two sentences why it matters *in this code*, then give a
concrete fix (code, not advice). If the rule clearly does not apply to this
language or code, mark false_positive_likely and say why. Write in {language}."""


def build_prompt(issues: list[dict[str, Any]], repo_root: str | Path = ".") -> str:
    parts = []
    for i in issues:
        path = component_path(i)
        line = int(i.get("line") or 1)
        snippet = read_snippet(Path(repo_root) / path, line, radius=12) or "(source not available)"
        parts.append(
            f"### {i.get('key')} — {i.get('severity')} {i.get('type')} — rule {i.get('rule')}\n"
            f"{path}:{line}\nMessage: {i.get('message')}\n```\n{snippet}\n```"
        )
    return "\n\n".join(parts)


def triage(client: AIClient, issues: list[dict[str, Any]], repo_root: str | Path = ".", language: str = "English") -> dict[str, Any]:
    if not issues:
        return {"overview": "No blocker or critical issues in recently changed files.", "items": []}
    return client.complete(SYSTEM.format(language=language), build_prompt(issues, repo_root), schema=SCHEMA, schema_name="sonar_triage")


def to_markdown(result: dict[str, Any], issues: list[dict[str, Any]], model_label: str = "") -> str:
    by_key = {i.get("key"): i for i in issues}
    lines = ["## SonarQube triage", "", result["overview"], ""]
    for item in result["items"]:
        issue = by_key.get(item["key"], {})
        where = f"`{component_path(issue)}`:{issue.get('line', '?')}" if issue else item["key"]
        flag = " · ⚠️ probably a false positive" if item["false_positive_likely"] else ""
        lines += [
            f"### {issue.get('severity', '?')} — {issue.get('message', item['key'])}",
            f"{where} · rule `{issue.get('rule', '?')}` · effort: {item['effort']}{flag}",
            "",
            item["why_it_matters"],
            "",
            "<details><summary>Proposed fix</summary>",
            "",
            item["fix"].strip(),
            "",
            "</details>",
            "",
        ]
    if model_label:
        lines.append(f"<sub>Generated by ai-devops-starter-kit · {model_label}</sub>")
    return "\n".join(lines).rstrip() + "\n"


def report_from_env_or_file(path: str | None) -> dict[str, Any]:
    if path:
        return load_report(path)
    host, project, token = (os.environ.get(k) for k in ("SONAR_HOST_URL", "SONAR_PROJECT_KEY", "SONAR_TOKEN"))
    if not (host and project and token):
        raise RuntimeError("pass --report FILE or set SONAR_HOST_URL, SONAR_PROJECT_KEY and SONAR_TOKEN")
    return fetch_report(host, project, token, os.environ.get("SONAR_BRANCH"))
