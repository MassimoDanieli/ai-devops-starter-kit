"""Command line entry point: ``python -m aikit <command>``.

Commands
  review     review the diff between --base and HEAD
  testgen    propose tests for code files changed since --base
  changelog  add a Keep-a-Changelog entry for commits since the last tag
  sonar      triage BLOCKER/CRITICAL SonarQube issues in recently changed files
  doctor     print the resolved AI configuration and exit

Common options: --out FILE (write Markdown), --comment (upsert a PR comment;
needs GITHUB_TOKEN, GITHUB_REPOSITORY and --pr or PR_NUMBER),
--language (output language, default English).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import changelog, gitutil, review, sonar, testgen
from .client import AIClient, AIConfig, AIConfigError


def _emit(markdown: str, args: argparse.Namespace, marker: str) -> None:
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(markdown)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    if args.comment:
        from .github import upsert_pr_comment

        repo = os.environ.get("GITHUB_REPOSITORY")
        pr = args.pr or os.environ.get("PR_NUMBER")
        if not (repo and pr):
            raise SystemExit("--comment needs GITHUB_REPOSITORY and --pr/PR_NUMBER")
        action = upsert_pr_comment(repo, int(pr), markdown, marker)
        print(f"PR comment {action}", file=sys.stderr)


def cmd_review(args: argparse.Namespace, client: AIClient) -> int:
    diff_text = gitutil.diff(args.base, args.head)
    ctx = Path(args.context).read_text(encoding="utf-8") if args.context else ""
    result = review.review_diff(client, diff_text, args.language, ctx)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    _emit(review.to_markdown(result, client.label), args, "<!-- aikit:review -->")
    if review.should_fail(result, args.fail_on):
        print(f"failing: findings at or above '{args.fail_on}'", file=sys.stderr)
        return 1
    return 0


def cmd_testgen(args: argparse.Namespace, client: AIClient) -> int:
    changed = [f for f in gitutil.changed_files(args.base, args.head) if testgen.is_code(f)]
    files = {}
    for f in changed[: args.max_files]:
        try:
            files[f] = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    tracked = gitutil.git("ls-files").splitlines()
    existing = [t for t in tracked if not testgen.is_code(t) and Path(t).suffix in testgen.CODE_SUFFIXES]
    result = testgen.propose(client, gitutil.diff(args.base, args.head), files, existing, args.language)
    if args.write:
        for p in testgen.write_proposals(result, args.write):
            print(f"wrote {p}", file=sys.stderr)
    _emit(testgen.to_markdown(result, client.label), args, "<!-- aikit:testgen -->")
    return 0


def cmd_changelog(args: argparse.Namespace, client: AIClient) -> int:
    since, tagged = gitutil.changelog_range()
    since = args.since or since
    version = args.version or tagged or "Unreleased"
    commits = gitutil.commits_since(since)
    result = changelog.summarise(client, commits, args.language)
    entry = changelog.render_entry(result, version)
    if args.dry_run:
        print(entry)
    else:
        changelog.insert_entry(args.file, entry)
        print(f"updated {args.file} ({len(commits)} commits since {since or 'the beginning'})", file=sys.stderr)
    return 0


def cmd_sonar(args: argparse.Namespace, client: AIClient) -> int:
    report = sonar.report_from_env_or_file(args.report)
    recent = None if args.all_files else gitutil.recently_changed_files(args.days)
    issues = sonar.select_issues(report, recent)
    result = sonar.triage(client, issues, ".", args.language)
    _emit(sonar.to_markdown(result, issues, client.label), args, "<!-- aikit:sonar -->")
    if args.fail_threshold and len(issues) >= args.fail_threshold:
        print(f"failing: {len(issues)} severe issues (threshold {args.fail_threshold})", file=sys.stderr)
        return 1
    return 0


def cmd_doctor(_: argparse.Namespace, client: AIClient) -> int:
    c = client.config
    print(json.dumps({"provider": c.provider, "model": c.model, "base_url": c.base_url, "max_tokens": c.max_tokens}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aikit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--language", default=os.environ.get("AI_LANGUAGE", "English"))
        sp.add_argument("--out", help="write Markdown here instead of stdout")
        sp.add_argument("--comment", action="store_true", help="create/update a PR comment")
        sp.add_argument("--pr", help="PR number (default: $PR_NUMBER)")

    r = sub.add_parser("review", help="review the PR diff")
    common(r)
    r.add_argument("--base", default=os.environ.get("BASE_REF", "origin/main"))
    r.add_argument("--head", default="HEAD")
    r.add_argument("--context", help="file with project conventions (e.g. CLAUDE.md, CONTRIBUTING.md)")
    r.add_argument("--json", help="also write the raw structured result here")
    r.add_argument("--fail-on", choices=review.SEVERITIES, help="exit 1 if a finding is at least this severe")
    r.set_defaults(func=cmd_review)

    t = sub.add_parser("testgen", help="propose tests for changed code")
    common(t)
    t.add_argument("--base", default=os.environ.get("BASE_REF", "origin/main"))
    t.add_argument("--head", default="HEAD")
    t.add_argument("--max-files", type=int, default=8)
    t.add_argument("--write", metavar="DIR", help="write proposed test files under DIR")
    t.set_defaults(func=cmd_testgen)

    c = sub.add_parser("changelog", help="add a changelog entry")
    c.add_argument("--language", default=os.environ.get("AI_LANGUAGE", "English"))
    c.add_argument("--version", help="entry title (default: tag at HEAD, else Unreleased)")
    c.add_argument("--since", help="git ref to start from (default: last tag)")
    c.add_argument("--file", default="CHANGELOG.md")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_changelog)

    s = sub.add_parser("sonar", help="triage SonarQube issues")
    common(s)
    s.add_argument("--report", help="SonarQube issues JSON (else uses SONAR_* env vars)")
    s.add_argument("--days", type=int, default=7, help="only files changed in the last N days")
    s.add_argument("--all-files", action="store_true", help="ignore git history filter")
    s.add_argument("--fail-threshold", type=int, default=0, help="exit 1 if at least N severe issues")
    s.set_defaults(func=cmd_sonar)

    d = sub.add_parser("doctor", help="show resolved AI configuration")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = AIClient(AIConfig.from_env())
    except AIConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    return args.func(args, client)


if __name__ == "__main__":
    sys.exit(main())
