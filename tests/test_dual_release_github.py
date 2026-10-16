#!/usr/bin/env python3
"""Synthetic, offline adversarial tests of dual-platform GitHub trust."""
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tools" / "verify-dual-release-github.py"
spec = importlib.util.spec_from_file_location("dual_auth", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
COMMIT = "a" * 40
REPO = "example/open-ipod-sync"
TAG = "v0.2.0-alpha.8"
VERSION = "0.2.0.alpha8"


def make_release(root):
    names = {
        f"open-ipod-sync-{COMMIT}-source.tar",
        f"ipod-sync_{VERSION}_amd64.deb",
        f"ipod-sync_{VERSION}_amd64.spdx.json",
        f"ipod-sync-ubuntu2604_{VERSION}_amd64.deb",
        f"ipod-sync-ubuntu2604_{VERSION}_amd64.spdx.json",
        "PROVENANCE.json", "CI-SHA256SUMS", "BUILD-MATERIALS.json",
        "TOOLCHAIN.json", "SHA256SUMS", "UBUNTU2604-PROVENANCE.json",
        "UBUNTU2604-CI-SHA256SUMS", "UBUNTU2604-BUILD-MATERIALS.json",
        "UBUNTU2604-TOOLCHAIN.json",
    }
    for name in names:
        (root / name).write_text(name)
    identity = {"source": {"repository": f"https://github.com/{REPO}"}}
    for name in ("PROVENANCE.json", "UBUNTU2604-PROVENANCE.json"):
        (root / name).write_text(json.dumps(identity))
    assert len(names) == 14
    return names


class FakeGitHub:
    def __init__(self, names):
        self.calls = []
        self.names = names
        self.immutable = True
        self.commit = COMMIT
        self.fail_on = None
        self.fail_spdx = False

    def __call__(self, *args):
        self.calls.append(args)
        if self.fail_on is not None and args[:len(self.fail_on)] == self.fail_on:
            raise subprocess.CalledProcessError(1, args)
        if self.fail_spdx and "--predicate-type" in args:
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ("release", "view"):
            return json.dumps({
                "tagName": TAG, "isDraft": False,
                "isPrerelease": True, "isImmutable": self.immutable,
                "assets": [{"name": name} for name in self.names],
            })
        if args[:2] == ("api", f"repos/{REPO}/git/ref/tags/{TAG}"):
            return json.dumps({"object": {"type": "tag", "sha": "b" * 40}})
        if args[:2] == ("api", f"repos/{REPO}/git/tags/{'b'*40}"):
            return json.dumps({"object": {"type": "commit", "sha": self.commit}})
        return ""


def expect_rejection(fn, expected_type=(ValueError, subprocess.CalledProcessError)):
    try:
        fn()
    except expected_type:
        return
    raise AssertionError("verification unexpectedly accepted unsafe input")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    names = make_release(root)
    original = module.gh
    try:
        github = FakeGitHub(names)
        module.gh = github
        module.authenticate(root, COMMIT, REPO, TAG)
        attests = [args for args in github.calls if args[:2] == ("attestation", "verify")]
        assert len(attests) == 15  # 13 supply-chain + 2 SPDX
        assert len([c for c in github.calls if c[:2] == ("release", "verify-asset")]) == 14
        assert all("--source-digest" in call and COMMIT in call for call in attests)
        assert all("--signer-workflow" in call and "--deny-self-hosted-runners" in call for call in attests)
        print("synthetic 14-asset GitHub authentication: PASS")

        github = FakeGitHub(names - {"TOOLCHAIN.json"})
        module.gh = github
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        assert not any(c[:2] == ("attestation", "verify") for c in github.calls)
        print("missing remote asset rejected: PASS")

        github = FakeGitHub(names)
        github.immutable = False
        module.gh = github
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        print("mutable remote release rejected: PASS")

        github = FakeGitHub(names)
        github.commit = "c" * 40
        module.gh = github
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        print("wrong annotated tag commit rejected: PASS")

        github = FakeGitHub(names)
        github.fail_on = ("attestation", "verify")
        module.gh = github
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        print("failed CI attestation rejected: PASS")

        github = FakeGitHub(names)
        github.fail_spdx = True
        module.gh = github
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        print("missing platform SPDX attestation rejected: PASS")

        github = FakeGitHub(names)
        module.gh = github
        bad = root / "UBUNTU2604-PROVENANCE.json"
        bad.write_text(json.dumps({"source": {"repository": "https://github.com/attacker/other"}}))
        expect_rejection(lambda: module.authenticate(root, COMMIT, REPO, TAG))
        print("wrong signed-source repository rejected: PASS")
    finally:
        module.gh = original

print("dual-platform GitHub authentication adversarial tests: PASS")
