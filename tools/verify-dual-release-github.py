#!/usr/bin/env python3
"""Fail-closed GitHub authenticity verification for the 14-asset release.

Run after offline verification of exactly the same downloaded assets.
Signed CI artifacts retain their bytes even where public filenames differ.
The generated public SHA256SUMS is covered by immutable-release asset
verification, not represented as a separately CI-attested file.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def gh(*args):
    completed = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True,
    )
    return completed.stdout


def gh_json(*args):
    return json.loads(gh(*args))


def tag_commit(repo, tag):
    ref = gh_json("api", f"repos/{repo}/git/ref/tags/{tag}")
    obj = ref["object"]
    for _ in range(8):
        sha = obj["sha"]
        require(bool(COMMIT_RE.fullmatch(sha)), "invalid GitHub tag object SHA")
        if obj["type"] == "commit":
            return sha
        require(obj["type"] == "tag", "unsupported GitHub tag object")
        obj = gh_json("api", f"repos/{repo}/git/tags/{sha}")["object"]
    raise ValueError("GitHub tag indirection exceeds limit")


def authenticate(directory, commit, repo, tag):
    require(bool(REPO_RE.fullmatch(repo)), "invalid repository slug")
    require(bool(TAG_RE.fullmatch(tag)), "invalid alpha release tag")
    require(bool(COMMIT_RE.fullmatch(commit)), "invalid source commit")
    require(directory.is_dir() and not directory.is_symlink(), "unsafe release directory")
    paths = list(directory.iterdir())
    require(len(paths) == 14, "expected exactly 14 release assets")
    require(all(p.is_file() and not p.is_symlink() for p in paths), "unsafe release assets")
    names = {p.name for p in paths}
    require(len(names) == 14 and "SHA256SUMS" in names, "invalid local asset set")
    source = f"open-ipod-sync-{commit}-source.tar"
    require(source in names, "source archive for expected commit missing")
    provenance = json.loads((directory / "PROVENANCE.json").read_text())
    ubuntu_provenance = json.loads((directory / "UBUNTU2604-PROVENANCE.json").read_text())
    url = f"https://github.com/{repo}"
    require(provenance["source"]["repository"].rstrip("/") == url,
            "Debian provenance repository mismatch")
    require(ubuntu_provenance["source"]["repository"].rstrip("/") == url,
            "Ubuntu provenance repository mismatch")

    release = gh_json(
        "release", "view", tag, "--repo", repo,
        "--json", "tagName,isDraft,isPrerelease,isImmutable,assets",
    )
    require(release["tagName"] == tag, "GitHub release tag mismatch")
    require(release["isDraft"] is False, "GitHub release is a draft")
    require(release["isPrerelease"] is True, "GitHub release is not a prerelease")
    require(release["isImmutable"] is True, "GitHub release is not immutable")
    remote = [asset["name"] for asset in release["assets"]]
    require(len(remote) == len(set(remote)) == 14 and set(remote) == names,
            "GitHub release asset set mismatch")
    require(tag_commit(repo, tag) == commit, "GitHub release tag commit mismatch")
    gh("release", "verify", tag, "--repo", repo)
    for name in sorted(names):
        gh("release", "verify-asset", tag, str(directory / name), "--repo", repo)

    signer = f"{repo}/.github/workflows/ci.yml"
    # Each of these is byte-identical to a CI-attested subject. The public
    # checksum manifest is newly constructed and is not a CI-signed subject.
    signed = sorted(names - {"SHA256SUMS"})
    for name in signed:
        gh(
            "attestation", "verify", str(directory / name),
            "--repo", repo, "--signer-workflow", signer,
            "--source-digest", commit, "--source-ref", "refs/heads/main",
            "--deny-self-hosted-runners",
        )
    debs = sorted(n for n in names if n.endswith("_amd64.deb"))
    require(len(debs) == 2, "expected two signed packages")
    for name in debs:
        gh(
            "attestation", "verify", str(directory / name),
            "--repo", repo,
            "--predicate-type", "https://spdx.dev/Document/v2.3",
            "--signer-workflow", signer, "--source-digest", commit,
            "--source-ref", "refs/heads/main",
            "--deny-self-hosted-runners",
        )
    print("Immutable GitHub release and 14 remote assets: PASS")
    print("Annotated tag/source identity: PASS")
    print("GitHub release asset digest verification: PASS")
    print("13 CI supply-chain attestations: PASS")
    print("Debian and Ubuntu SPDX attestations: PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        require(bool(REPO_RE.fullmatch(args.repo)), "invalid repository")
        require(bool(TAG_RE.fullmatch(args.tag)), "invalid release tag")
        require(bool(COMMIT_RE.fullmatch(args.expected_commit)), "invalid source commit")
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "verify-dual-release.py"),
             str(args.release_dir), "--expected-commit", args.expected_commit],
            check=True,
        )
        authenticate(args.release_dir, args.expected_commit, args.repo, args.tag)
    except (OSError, ValueError, KeyError, TypeError,
            json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print("Online dual-platform consumer verification: PASS")


if __name__ == "__main__":
    main()
