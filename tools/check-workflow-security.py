#!/usr/bin/env python3

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

ALLOWED_REMOTE_OWNERS = {
    "actions",
    "github",
    "zizmorcore",
    "ossf",
}

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

USES = re.compile(
    r"^\s*uses:\s*([^\s#]+)",
    re.MULTILINE,
)

IMAGE = re.compile(
    r"^\s*image:\s*([^\s#]+)",
    re.MULTILINE,
)

RUNS_ON_LATEST = re.compile(
    r"^\s*runs-on:\s*['\"]?[^#\n]*-latest['\"]?\s*(?:#.*)?$",
    re.MULTILINE,
)

WRITE_ALL = re.compile(
    r"^\s*permissions:\s*write-all\s*(?:#.*)?$",
    re.MULTILINE,
)

errors: list[str] = []


def error(path: Path, message: str) -> None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path

    errors.append(f"{rel}: {message}")


workflow_paths = sorted(
    list(WORKFLOWS.glob("*.yml"))
    + list(WORKFLOWS.glob("*.yaml"))
)

if not workflow_paths:
    raise SystemExit("ERROR: no GitHub Actions workflows found")


for path in workflow_paths:
    text = path.read_text()
    lines = text.splitlines()

    if re.search(r"^\s*pull_request_target\s*:", text, re.MULTILINE):
        error(
            path,
            "pull_request_target is forbidden unless explicitly security-reviewed",
        )

    if WRITE_ALL.search(text):
        error(path, "permissions: write-all is forbidden")

    if RUNS_ON_LATEST.search(text):
        error(path, "floating *-latest runner label is forbidden")

    for match in USES.finditer(text):
        ref = match.group(1).strip("'\"")

        if ref.startswith("./"):
            continue

        if ref.startswith("docker://"):
            image_ref = ref.removeprefix("docker://")

            if "@sha256:" not in image_ref:
                error(path, f"Docker action is not digest-pinned: {ref}")
                continue

            _, digest = image_ref.rsplit("@", 1)

            if not DIGEST.fullmatch(digest):
                error(path, f"invalid Docker action digest: {ref}")

            continue

        target, sep, revision = ref.rpartition("@")

        if not sep:
            error(path, f"remote action has no immutable revision: {ref}")
            continue

        if not FULL_SHA.fullmatch(revision):
            error(
                path,
                f"remote action is not pinned to a full 40-character SHA: {ref}",
            )
            continue

        owner = target.split("/", 1)[0]

        if owner not in ALLOWED_REMOTE_OWNERS:
            error(
                path,
                f"remote action owner is not allow-listed: {owner!r} ({ref})",
            )

    for match in IMAGE.finditer(text):
        image = match.group(1).strip("'\"")

        if "${{" in image:
            error(path, f"dynamic container image is forbidden: {image}")
            continue

        if "@sha256:" not in image:
            error(path, f"container image is not digest-pinned: {image}")
            continue

        _, digest = image.rsplit("@", 1)

        if not DIGEST.fullmatch(digest):
            error(path, f"invalid container digest: {image}")

    for index, line in enumerate(lines):
        match = re.match(
            r"^\s*uses:\s*actions/checkout@([0-9a-f]{40})",
            line,
        )

        if not match:
            continue

        following = "\n".join(lines[index + 1:index + 10])

        if not re.search(
            r"^\s*persist-credentials:\s*false\s*(?:#.*)?$",
            following,
            re.MULTILINE,
        ):
            error(
                path,
                "actions/checkout must explicitly set "
                "persist-credentials: false",
            )


if errors:
    print("workflow security policy: FAIL", file=sys.stderr)

    for item in errors:
        print(f"  - {item}", file=sys.stderr)

    raise SystemExit(1)


print(f"workflow security policy: PASS ({len(workflow_paths)} workflows)")
