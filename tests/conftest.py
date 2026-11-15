import subprocess
from pathlib import Path

import pytest

from aikit.client import AIClient, AIConfig


def fake_client(answer):
    """AIClient whose model always returns ``answer`` (dict or str) and records prompts."""
    seen = []

    def responder(system, user, schema):
        seen.append({"system": system, "user": user, "schema": schema})
        return answer(system, user, schema) if callable(answer) else answer

    client = AIClient(AIConfig(provider="fake", model="fake"), fake_responder=responder)
    client.seen = seen
    return client


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    """A throwaway git repo with a main branch and a feature commit."""

    def run(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Tester")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    run("add", ".")
    run("commit", "-q", "-m", "feat: add calculator")
    run("tag", "v1.0.0")
    run("checkout", "-q", "-b", "feature")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    return a / b\n")
    run("add", ".")
    run("commit", "-q", "-m", "feat: add division", "-m", "Needed for the report page.")
    (tmp_path / "README.md").write_text("docs\n")
    run("add", ".")
    run("commit", "-q", "-m", "docs: readme")
    monkeypatch.chdir(tmp_path)
    return tmp_path
