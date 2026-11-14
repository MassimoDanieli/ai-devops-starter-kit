import datetime as dt
import json

from aikit import changelog, gitutil, review, sonar, testgen
from aikit.__main__ import main

from .conftest import fake_client

REVIEW_ANSWER = {
    "summary": "Adds integer division.",
    "verdict": "needs_changes",
    "findings": [
        {
            "file": "calc.py",
            "line": 6,
            "severity": "minor",
            "category": "maintainability",
            "title": "Missing docstring",
            "explanation": "x",
            "suggested_fix": "",
        },
        {
            "file": "calc.py",
            "line": 6,
            "severity": "major",
            "category": "bug",
            "title": "Division by zero",
            "explanation": "b can be 0",
            "suggested_fix": "if b == 0: raise ValueError",
        },
    ],
}


# --- git helpers -----------------------------------------------------------


def test_git_helpers(repo):
    assert gitutil.changed_files("main") == ["README.md", "calc.py"]
    assert "def div" in gitutil.diff("main")
    assert gitutil.last_tag() == "v1.0.0"
    commits = gitutil.commits_since("v1.0.0")
    assert [c.subject for c in commits] == ["docs: readme", "feat: add division"]
    assert commits[1].body == "Needed for the report page."
    assert "calc.py" in gitutil.recently_changed_files(7)
    assert "    5 | def div(a, b):" in gitutil.read_snippet(repo / "calc.py", 5, radius=1)


# --- review ----------------------------------------------------------------


def test_review_sends_diff_and_renders_sorted(repo):
    client = fake_client(REVIEW_ANSWER)
    result = review.review_diff(client, gitutil.diff("main"), language="Italian")
    assert "def div" in client.seen[0]["user"]
    assert "Italian" in client.seen[0]["system"]
    md = review.to_markdown(result, "fake:fake")
    assert md.index("Division by zero") < md.index("Missing docstring")
    assert "🔴 Needs changes" in md
    assert review.should_fail(result, "major")
    assert not review.should_fail(result, "critical")
    assert not review.should_fail(result, None)


def test_review_skips_model_on_empty_diff():
    client = fake_client(lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert review.review_diff(client, "   ")["findings"] == []


def test_review_truncates_huge_diffs():
    prompt = review.build_prompt("x" * (review.MAX_DIFF_CHARS + 10))
    assert "[diff truncated" in prompt


def test_cli_review_writes_files_and_fails_on_threshold(repo, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "fake")
    monkeypatch.setattr("aikit.__main__.AIClient", lambda cfg: fake_client(REVIEW_ANSWER))
    rc = main(["review", "--base", "main", "--out", "r.md", "--json", "r.json", "--fail-on", "major"])
    assert rc == 1
    assert "Division by zero" in (repo / "r.md").read_text()
    assert json.loads((repo / "r.json").read_text())["verdict"] == "needs_changes"


# --- changelog -------------------------------------------------------------


def test_changelog_entry_inserted_above_previous(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog.HEADER + "\n## [1.0.0] - 2025-07-18\n\n### Added\n- first\n")
    result = {"highlights": "Division!", "added": ["Division (abc123)"], "changed": [], "fixed": [], "removed": [], "security": []}
    changelog.insert_entry(path, changelog.render_entry(result, "1.1.0", dt.date(2026, 11, 14)))
    text = path.read_text()
    assert text.index("## [1.1.0] - 2026-11-14") < text.index("## [1.0.0]")
    assert "### Added\n- Division (abc123)" in text
    assert "### Fixed" not in text


def test_changelog_creates_file_and_handles_no_changes(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    empty = {"highlights": "", **{s.lower(): [] for s in changelog.SECTIONS}}
    changelog.insert_entry(path, changelog.render_entry(empty, "Unreleased", dt.date(2026, 1, 1)))
    assert path.read_text().startswith("# Changelog")
    assert "_No user-facing changes._" in path.read_text()


def test_changelog_prompt_includes_bodies(repo):
    commits = gitutil.commits_since("v1.0.0")
    client = fake_client({"highlights": "", **{s.lower(): [] for s in changelog.SECTIONS}})
    changelog.summarise(client, commits)
    assert "Needed for the report page." in client.seen[0]["user"]


# --- testgen ---------------------------------------------------------------


def test_is_code_excludes_tests_and_docs():
    assert testgen.is_code("src/app.py")
    assert not testgen.is_code("tests/test_app.py")
    assert not testgen.is_code("web/app.spec.ts")
    assert not testgen.is_code("README.md")


def test_write_proposals_refuses_path_escape(tmp_path):
    result = {
        "proposals": [
            {
                "target_file": "calc.py",
                "test_file": "tests/test_calc.py",
                "framework": "pytest",
                "covers": ["div"],
                "code": "def test(): pass",
            },
            {"target_file": "calc.py", "test_file": "../../evil.py", "framework": "pytest", "covers": [], "code": "x"},
        ]
    }
    written = testgen.write_proposals(result, tmp_path / "out")
    assert [p.name for p in written] == ["test_calc.py"]
    assert not (tmp_path / "evil.py").exists()


# --- sonar -----------------------------------------------------------------

REPORT = {
    "issues": [
        {
            "key": "K1",
            "rule": "python:S3776",
            "severity": "CRITICAL",
            "component": "proj:calc.py",
            "line": 5,
            "message": "Too complex",
            "type": "CODE_SMELL",
        },
        {
            "key": "K2",
            "rule": "python:S1",
            "severity": "MAJOR",
            "component": "proj:calc.py",
            "line": 1,
            "message": "meh",
            "type": "CODE_SMELL",
        },
        {"key": "K3", "rule": "python:S2", "severity": "BLOCKER", "component": "proj:old.py", "line": 9, "message": "old", "type": "BUG"},
    ]
}


def test_sonar_selects_severe_recent_issues():
    picked = sonar.select_issues(REPORT, {"calc.py"})
    assert [i["key"] for i in picked] == ["K1"]
    everything = sonar.select_issues(REPORT, None)
    assert [i["key"] for i in everything] == ["K3", "K1"]  # BLOCKER before CRITICAL


def test_sonar_triage_includes_code_and_renders(repo):
    issues = sonar.select_issues(REPORT, {"calc.py"})
    answer = {
        "overview": "One issue.",
        "items": [{"key": "K1", "why_it_matters": "w", "fix": "f", "effort": "small", "false_positive_likely": True}],
    }
    client = fake_client(answer)
    result = sonar.triage(client, issues, repo)
    assert "def div(a, b):" in client.seen[0]["user"]
    md = sonar.to_markdown(result, issues)
    assert "`calc.py`:5" in md and "false positive" in md


def test_cli_sonar_with_report_file(repo, monkeypatch):
    (repo / "report.json").write_text(json.dumps(REPORT))
    answer = {"overview": "ok", "items": []}
    monkeypatch.setattr("aikit.__main__.AIClient", lambda cfg: fake_client(answer))
    assert main(["sonar", "--report", "report.json", "--out", "s.md", "--fail-threshold", "1"]) == 1
    assert "SonarQube triage" in (repo / "s.md").read_text()


def test_cli_reports_config_errors(monkeypatch, capsys):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("AI_MODEL", raising=False)
    assert main(["doctor"]) == 2
    assert "AI_MODEL" in capsys.readouterr().err


def test_changelog_range_on_tag_and_off_tag(repo):
    import subprocess

    assert gitutil.changelog_range() == ("v1.0.0", None)
    subprocess.run(["git", "tag", "v1.1.0"], cwd=repo, check=True)
    assert gitutil.changelog_range() == ("v1.0.0", "v1.1.0")


def test_cli_changelog_uses_tag_as_version(repo, monkeypatch):
    import subprocess

    subprocess.run(["git", "tag", "v1.1.0"], cwd=repo, check=True)
    answer = {"highlights": "", "added": ["Division (x)"], "changed": [], "fixed": [], "removed": [], "security": []}
    monkeypatch.setattr("aikit.__main__.AIClient", lambda cfg: fake_client(answer))
    assert main(["changelog"]) == 0
    assert "## [v1.1.0]" in (repo / "CHANGELOG.md").read_text()
