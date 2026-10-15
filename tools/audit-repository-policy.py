#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


EXPECTED_REQUIRED_CHECKS = {
    "Public source sanity — Python 3.9",
    "Debian 11 package build + audit",
    "Debian 11 reproducibility gate",
    "Debian 11 package lifecycle",
    "Ubuntu host compatibility — ubuntu-24.04",
    "Ubuntu host compatibility — ubuntu-26.04",
    "Workflow policy and actionlint",
    "zizmor GitHub Actions security",
    "CodeQL",
    "CodeQL — C/C++",
    "CodeQL — Python",
    "Dependency vulnerability review",
}

MAIN_ONLY_ATTESTATION = "GitHub artifact attestations"

EXPECTED_ACTION_PATTERNS = {
    "zizmorcore/zizmor-action@*",
    "ossf/scorecard-action@*",
}

API_VERSION = "2026-03-10"


class AuditError(RuntimeError):
    pass


def run_json(args: list[str]) -> Any:
    proc = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise AuditError(
            "command failed: {}\n{}".format(
                " ".join(args),
                detail or "(no diagnostic output)",
            )
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError(
            "command returned invalid JSON: {}\n{}".format(
                " ".join(args),
                proc.stdout,
            )
        ) from exc


def api(repo: str, suffix: str) -> Any:
    endpoint = f"repos/{repo}"

    if suffix:
        endpoint += "/" + suffix.lstrip("/")

    return run_json(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
            endpoint,
        ]
    )


def repo_name(explicit: str | None) -> str:
    if explicit:
        return explicit

    doc = run_json(
        [
            "gh",
            "repo",
            "view",
            "--json",
            "nameWithOwner",
        ]
    )

    value = doc.get("nameWithOwner")

    if not isinstance(value, str) or "/" not in value:
        raise AuditError(
            "unable to determine repository identity"
        )

    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def rule_by_type(ruleset: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [
        rule
        for rule in ruleset.get("rules", [])
        if rule.get("type") == kind
    ]

    require(
        len(matches) == 1,
        "expected exactly one {!r} rule; found {}".format(
            kind,
            len(matches),
        ),
    )

    return matches[0]


def unique_ruleset(
    rulesets: list[dict[str, Any]],
    name: str,
    target: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in rulesets
        if (
            item.get("name") == name
            and item.get("target") == target
        )
    ]

    require(
        len(matches) == 1,
        "expected exactly one {!r} {} ruleset; found {}".format(
            name,
            target,
            len(matches),
        ),
    )

    return matches[0]


def audit_main_policy(
    repo: str,
    repository: dict[str, Any],
    rulesets: list[dict[str, Any]],
) -> None:
    summary = unique_ruleset(
        rulesets,
        "Protect main",
        "branch",
    )

    ruleset = api(
        repo,
        f"rulesets/{summary['id']}",
    )

    require(
        ruleset.get("enforcement") == "active",
        "Protect main is not active",
    )

    require(
        ruleset.get("bypass_actors") == [],
        "Protect main has bypass actors",
    )

    refs = (
        ruleset.get("conditions", {})
        .get("ref_name", {})
    )

    require(
        refs.get("include") == ["refs/heads/main"],
        "Protect main does not target only refs/heads/main",
    )

    require(
        refs.get("exclude") == [],
        "Protect main has unexpected exclusions",
    )

    rule_by_type(
        ruleset,
        "deletion",
    )

    rule_by_type(
        ruleset,
        "non_fast_forward",
    )

    pull_request = rule_by_type(
        ruleset,
        "pull_request",
    ).get(
        "parameters",
        {},
    )

    require(
        pull_request.get("allowed_merge_methods") == ["merge"],
        "main ruleset is not merge-commit-only",
    )

    require(
        pull_request.get("required_approving_review_count") == 0,
        "solo-maintainer approving-review count changed",
    )

    require(
        pull_request.get("require_code_owner_review") is False,
        "CODEOWNER approval unexpectedly required",
    )

    require(
        pull_request.get("required_review_thread_resolution") is True,
        "review-thread resolution is not required",
    )

    statuses = rule_by_type(
        ruleset,
        "required_status_checks",
    ).get(
        "parameters",
        {},
    )

    require(
        statuses.get("strict_required_status_checks_policy") is True,
        "required checks are not strict/up-to-date",
    )

    actual_checks = {
        item.get("context")
        for item in statuses.get(
            "required_status_checks",
            [],
        )
    }

    require(
        actual_checks == EXPECTED_REQUIRED_CHECKS,
        "required-check contract mismatch\nexpected={}\nactual={}".format(
            sorted(EXPECTED_REQUIRED_CHECKS),
            sorted(actual_checks),
        ),
    )

    require(
        MAIN_ONLY_ATTESTATION not in actual_checks,
        "main-only attestation job is incorrectly PR-required",
    )

    expected_repo = {
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_rebase_merge": False,
        "allow_auto_merge": False,
        "delete_branch_on_merge": True,
    }

    for key, expected in expected_repo.items():
        require(
            repository.get(key) == expected,
            "{} expected={!r}, actual={!r}".format(
                key,
                expected,
                repository.get(key),
            ),
        )

    print("main branch ruleset: PASS")
    print("required PR checks: 12 — PASS")
    print("merge-commit-only repository policy: PASS")


def audit_actions(repo: str) -> None:
    actions = api(
        repo,
        "actions/permissions",
    )

    require(
        actions.get("enabled") is True,
        "GitHub Actions is disabled",
    )

    require(
        actions.get("allowed_actions") == "selected",
        "Actions policy is not selected-actions-only",
    )

    workflow = api(
        repo,
        "actions/permissions/workflow",
    )

    require(
        workflow.get("default_workflow_permissions") == "read",
        "default GITHUB_TOKEN permission is not read-only",
    )

    require(
        workflow.get("can_approve_pull_request_reviews") is False,
        "workflow token can approve pull-request reviews",
    )

    selected = api(
        repo,
        "actions/permissions/selected-actions",
    )

    require(
        selected.get("github_owned_allowed") is True,
        "GitHub-owned actions are not allowed",
    )

    require(
        selected.get("verified_allowed") is False,
        "all verified Marketplace actions are unexpectedly allowed",
    )

    patterns = set(
        selected.get(
            "patterns_allowed",
            [],
        )
    )

    require(
        patterns == EXPECTED_ACTION_PATTERNS,
        "selected action pattern contract mismatch\n"
        "expected={}\nactual={}".format(
            sorted(EXPECTED_ACTION_PATTERNS),
            sorted(patterns),
        ),
    )

    fork_policy = api(
        repo,
        "actions/permissions/fork-pr-contributor-approval",
    )

    require(
        fork_policy.get("approval_policy")
        == "first_time_contributors",
        "fork PR workflow approval policy changed",
    )

    print("selected Actions allowlist: PASS")
    print("default GITHUB_TOKEN read-only: PASS")
    print("workflow PR approval disabled: PASS")
    print("first-time-contributor workflow approval: PASS")


def audit_security(
    repo: str,
    repository: dict[str, Any],
) -> None:
    security = repository.get(
        "security_and_analysis",
        {},
    )

    for name in (
        "secret_scanning",
        "secret_scanning_push_protection",
        "dependabot_security_updates",
    ):
        status = (
            security.get(
                name,
                {},
            ).get(
                "status"
            )
        )

        require(
            status == "enabled",
            "{} expected enabled; actual={!r}".format(
                name,
                status,
            ),
        )

    pvr = api(
        repo,
        "private-vulnerability-reporting",
    )

    require(
        pvr.get("enabled") is True,
        "private vulnerability reporting is disabled",
    )

    print("secret scanning: PASS")
    print("push protection: PASS")
    print("Dependabot security updates: PASS")
    print("private vulnerability reporting: PASS")

    # These advanced Secret Protection capabilities are not part of the
    # enforced repository-policy contract. Do not echo GitHub-returned
    # capability values into audit output.
    print(
        "generic/non-provider secret patterns: "
        "NOT POLICY-REQUIRED"
    )
    print(
        "secret validity checks: "
        "NOT POLICY-REQUIRED"
    )

    for name, endpoint in (
        (
            "secret-scanning",
            "secret-scanning/alerts?state=open&per_page=100",
        ),
        (
            "dependabot",
            "dependabot/alerts?state=open&per_page=100",
        ),
        (
            "code-scanning",
            "code-scanning/alerts?state=open&per_page=100",
        ),
    ):
        alerts = api(
            repo,
            endpoint,
        )

        require(
            isinstance(alerts, list),
            f"{name} alerts API returned unexpected data",
        )

        require(
            not alerts,
            "{} has {} open alert(s)".format(
                name,
                len(alerts),
            ),
        )

        print(
            f"{name} open alerts: 0 — PASS"
        )


def audit_release_environment(repo: str) -> None:
    env = api(
        repo,
        "environments/release",
    )

    deployment = (
        env.get("deployment_branch_policy")
        or {}
    )

    require(
        deployment.get("protected_branches") is False,
        "release environment is not using custom branch policy",
    )

    require(
        deployment.get("custom_branch_policies") is True,
        "release custom branch policies are disabled",
    )

    reviewer_rules = [
        rule
        for rule in env.get(
            "protection_rules",
            [],
        )
        if rule.get("type") == "required_reviewers"
    ]

    require(
        len(reviewer_rules) == 1,
        "expected exactly one release reviewer rule",
    )

    owner = repo.split(
        "/",
        1,
    )[0]

    reviewers = {
        (
            item.get("reviewer")
            or {}
        ).get("login")
        for item in reviewer_rules[0].get(
            "reviewers",
            [],
        )
        if item.get("type") == "User"
    }

    require(
        owner in reviewers,
        "repository owner is not a release-environment reviewer",
    )

    require(
        reviewer_rules[0].get("prevent_self_review") is False,
        "release environment would block solo-maintainer approval",
    )

    policies = api(
        repo,
        "environments/release/deployment-branch-policies",
    ).get(
        "branch_policies",
        [],
    )

    require(
        len(policies) == 1,
        "release environment must have exactly one deployment branch policy",
    )

    require(
        policies[0].get("name") == "main",
        "release environment is not main-only",
    )

    require(
        policies[0].get("type") in {
            None,
            "branch",
        },
        "release environment deployment policy is not branch-scoped",
    )

    print("release reviewer protection: PASS")
    print("release environment main-only: PASS")


def audit_release_policy(
    repo: str,
    rulesets: list[dict[str, Any]],
) -> None:
    immutable = api(
        repo,
        "immutable-releases",
    )

    require(
        immutable.get("enabled") is True,
        "repository immutable releases are disabled",
    )

    summary = unique_ruleset(
        rulesets,
        "Protect release tags",
        "tag",
    )

    ruleset = api(
        repo,
        f"rulesets/{summary['id']}",
    )

    require(
        ruleset.get("enforcement") == "active",
        "Protect release tags is not active",
    )

    require(
        ruleset.get("bypass_actors") == [],
        "release-tag ruleset has bypass actors",
    )

    refs = (
        ruleset.get("conditions", {})
        .get("ref_name", {})
    )

    require(
        refs.get("include") == ["refs/tags/v*"],
        "release-tag ruleset target changed",
    )

    require(
        refs.get("exclude") == [],
        "release-tag ruleset has unexpected exclusions",
    )

    rule_types = {
        rule.get("type")
        for rule in ruleset.get(
            "rules",
            [],
        )
    }

    require(
        rule_types == {
            "update",
            "deletion",
        },
        "release-tag rule contract mismatch: {!r}".format(
            sorted(rule_types),
        ),
    )

    require(
        "creation" not in rule_types,
        "release-tag creation is blocked",
    )

    print("repository immutable releases: PASS")
    print("new v* tag creation allowed: PASS")
    print("existing v* tag update/retarget blocked: PASS")
    print("existing v* tag deletion blocked: PASS")
    print("release-tag bypass actors: NONE")



def audit_local_contract(root: Path) -> None:
    workflow = (
        root
        / ".github"
        / "workflows"
        / "release.yml"
    ).read_text()

    for token in (
        "workflow_dispatch:",
        "name: Publish immutable release",
        "name: release",
        'git tag -a "$TAG"',
        'gh release create "$TAG"',
        "--verify-tag",
        'if not doc["isImmutable"]',
    ):
        require(
            token in workflow,
            f"release workflow contract missing: {token}",
        )

    print("release workflow policy contract: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of the open-ipod-sync "
            "GitHub repository policy."
        )
    )

    parser.add_argument(
        "--repo",
        help=(
            "GitHub repository in OWNER/NAME form. "
            "Defaults to the current gh repository."
        ),
    )

    args = parser.parse_args()

    repo = repo_name(
        args.repo
    )

    root = Path(
        __file__
    ).resolve().parent.parent

    print(
        "repository:",
        repo,
    )

    repository = api(
        repo,
        "",
    )

    require(
        repository.get("full_name") == repo,
        "repository identity mismatch",
    )

    require(
        repository.get("visibility") == "public",
        "repository is not public",
    )

    rulesets = api(
        repo,
        "rulesets?includes_parents=true",
    )

    require(
        isinstance(rulesets, list),
        "ruleset API returned unexpected data",
    )

    audit_main_policy(
        repo,
        repository,
        rulesets,
    )

    audit_actions(
        repo,
    )

    audit_security(
        repo,
        repository,
    )

    audit_release_environment(
        repo,
    )

    audit_release_policy(
        repo,
        rulesets,
    )

    audit_local_contract(
        root,
    )

    print()
    print(
        "repository policy live audit: PASS"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except AuditError as exc:
        print(
            "ERROR:",
            exc,
            file=sys.stderr,
        )
        raise SystemExit(1)
