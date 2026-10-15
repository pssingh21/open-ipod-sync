# Repository policy

This document records the security, merge, CI, and release controls enforced
for the `open-ipod-sync` GitHub repository.

The GitHub-hosted configuration is the enforcement layer. This document is the
version-controlled policy contract and operator reference.

The live configuration can be checked read-only with:

```bash
python3 tools/audit-repository-policy.py
```

The audit uses the GitHub CLI and does not modify repository settings.

## Main branch

`main` is protected by the active `Protect main` repository ruleset.

The ruleset:

- has no bypass actors;
- prevents deletion of `main`;
- prevents non-fast-forward updates;
- requires changes to enter through pull requests;
- requires review conversations to be resolved;
- uses a solo-maintainer approval model with zero mandatory approving reviews;
- does not require CODEOWNER approval;
- permits merge commits only; and
- requires the pull-request branch to be up to date with `main`.

The repository itself is also configured to:

- allow merge commits;
- disable squash merges;
- disable rebase merges;
- disable auto-merge; and
- delete merged branches automatically.

CODEOWNERS remains useful for ownership visibility and future multi-maintainer
operation even though CODEOWNER approval is not currently mandatory.

## Required pull-request checks

The following checks are required before a pull request can merge:

1. `Public source sanity — Python 3.9`
2. `Debian 11 package build + audit`
3. `Debian 11 reproducibility gate`
4. `Debian 11 package lifecycle`
5. `Ubuntu host compatibility — ubuntu-24.04`
6. `Ubuntu host compatibility — ubuntu-26.04`
7. `Workflow policy and actionlint`
8. `zizmor GitHub Actions security`
9. `CodeQL`
10. `CodeQL — C/C++`
11. `CodeQL — Python`
12. `Dependency vulnerability review`

`GitHub artifact attestations` is deliberately not a pull-request-required
check. That job is intentionally restricted to pushes to `main`, where the
canonical post-merge artifacts are created and attested.

## GitHub Actions policy

GitHub Actions is enabled with an allowlist policy.

The repository permits:

- GitHub-owned actions;
- `zizmorcore/zizmor-action@*`; and
- `ossf/scorecard-action@*`.

Arbitrary verified Marketplace actions are not globally allowed.

Repository workflows additionally pin action references to immutable commit
SHAs through the workflow-security policy in the source tree.

Default `GITHUB_TOKEN` permissions are read-only and workflows are not allowed
to approve pull-request reviews.

Pull requests from first-time external contributors require workflow approval.

Individual jobs may request narrowly scoped permissions where required for
their function, such as artifact attestations or release publication.

## Security controls

The repository has the following supported GitHub security controls enabled:

- secret scanning;
- secret-scanning push protection;
- Dependabot security updates;
- CodeQL/code scanning; and
- private vulnerability reporting.

Generic/non-provider secret patterns and secret validity checks are currently
reported as disabled by GitHub for this user-owned public repository. They are
treated as platform/account capability state rather than as an enforced policy
requirement. If GitHub later makes those controls available for this repository,
enabling them is compatible with this policy.

Security-sensitive reports should use GitHub private vulnerability reporting.
See [`../SECURITY.md`](../SECURITY.md).

## Release environment

Release publication is protected by the GitHub `release` environment.

The environment:

- requires reviewer approval;
- uses a custom deployment-branch policy;
- permits deployment from `main` only; and
- retains self-review capability because the repository currently has one
  maintainer.

The release workflow is manually dispatched and the publication job enters this
environment before creating the release tag and release.

## Release immutability

Repository-level immutable releases are enabled.

This protects releases created after the setting was enabled. Historical
releases created before immutable-release enforcement may continue to report a
non-immutable release object; this is expected historical state.

The active `Protect release tags` tag ruleset applies to:

```text
refs/tags/v*
```

It has no bypass actors and:

- allows creation of a new matching tag;
- blocks updates or retargeting of an existing matching tag; and
- blocks deletion of an existing matching tag.

Creation must remain allowed because the release workflow creates a new
annotated version tag as part of publication.

The workflow independently verifies that newly published releases are immutable.

## Release evidence

The release workflow publishes the consumer-verification evidence described in
[`RELEASE-RUNBOOK.md`](RELEASE-RUNBOOK.md).

Checksum files provide integrity and internal consistency. Authenticity comes
from the trusted GitHub release/tag identity and GitHub artifact attestations.
Independent reproducible rebuilding provides an additional consistency check.

## Source-data safety boundary

Repository-policy auditing is independent of synchronization data.

`tools/audit-repository-policy.py` accesses GitHub repository metadata only. It
does not inspect or modify:

- the configured music source;
- NAS content;
- an iPod mount;
- device databases; or
- synchronization transaction state.

The project-wide invariant remains unchanged: the configured source music
filesystem is strictly read-only and must never be mutated by synchronization,
validation, hashing, probing, recovery, or audit operations.

## Auditing

Run the live policy audit from a clean checkout with an authenticated GitHub
CLI session:

```bash
python3 tools/audit-repository-policy.py
```

Optionally specify a repository explicitly:

```bash
python3 tools/audit-repository-policy.py \
  --repo pssingh21/open-ipod-sync
```

The live audit is intentionally not part of ordinary CI. Validating
administrator-level repository configuration from CI would require additional
GitHub API authority and would unnecessarily increase CI privilege.

Instead:

- CI checks the version-controlled policy contract offline; and
- maintainers run the live read-only audit when repository policy changes and
  during security reviews.

## Changing this policy

Repository-policy changes should be deliberate and reviewed like code changes.

At minimum:

1. update the GitHub control;
2. run `python3 tools/audit-repository-policy.py`;
3. update this document if the intended contract changed;
4. run `./tools/public-sanity-check.sh`;
5. open a pull request;
6. require all configured pull-request checks to pass; and
7. after merge, verify the `main` push CI run, including
   `GitHub artifact attestations`.
