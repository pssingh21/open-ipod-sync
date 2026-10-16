#!/usr/bin/env python3
"""Synthetic release assembly and adversarial input tests."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prepare-dual-release-assets.py"
COMMIT = 'a' * 40
DEB_VERSION = '0.2.0~alpha7'
PUBLIC_VERSION = '0.2.0.alpha7'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_ci(root, platform):
    root.mkdir()
    deb = f'ipod-sync_{DEB_VERSION}_amd64.deb'
    sbom = f'ipod-sync_{DEB_VERSION}_amd64.spdx.json'
    archive = f'open-ipod-sync-{COMMIT}-source.tar'
    (root / deb).write_bytes(platform.encode() + b'-deb')
    (root / sbom).write_bytes(platform.encode() + b'-spdx')
    (root / archive).write_bytes(b'shared-source')
    (root / 'PROVENANCE.json').write_text(json.dumps({
        'source': {'git_commit': COMMIT},
        'subject': {'name': deb, 'sha256': digest(root / deb)},
        'sbom': {'name': sbom, 'sha256': digest(root / sbom)},
        'build': {'environment': platform},
    }))
    (root / 'BUILD-MATERIALS.json').write_text(json.dumps({
        'source': {'commit': COMMIT, 'archive_sha256': digest(root / archive)}
    }))
    (root / 'TOOLCHAIN.json').write_text('{}')
    write_checksums(root)


def write_checksums(root):
    (root / 'SHA256SUMS').write_text(''.join(
        f'{digest(p)}  {p.name}\n' for p in sorted(root.iterdir())
        if p.name != 'SHA256SUMS'
    ))


def attempt(root, output, public_version=PUBLIC_VERSION):
    return subprocess.run([
        sys.executable, str(SCRIPT),
        '--debian-ci', str(root / 'debian'),
        '--ubuntu-ci', str(root / 'ubuntu'),
        '--output', str(root / output),
        '--deb-version', DEB_VERSION,
        '--public-version', public_version,
        '--commit', COMMIT,
    ], capture_output=True, text=True)


def fresh(root):
    make_ci(root / 'debian', 'debian-11-amd64-snapshot-20260830T235959Z')
    make_ci(root / 'ubuntu', 'ubuntu-26.04-amd64')


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)
    result = attempt(root, 'release')
    assert result.returncode == 0, result.stderr
    out = root / 'release'
    assert len(list(out.iterdir())) == 14
    expected = {line.split('  ', 1)[1] for line in (out / 'SHA256SUMS').read_text().splitlines()}
    assert expected == {p.name for p in out.iterdir()} - {'SHA256SUMS'}
    assert digest(out / f'open-ipod-sync-{COMMIT}-source.tar') == digest(root / 'debian' / f'open-ipod-sync-{COMMIT}-source.tar')
    print('exact 14-asset release layout: PASS')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)
    target = root / 'ubuntu' / f'ipod-sync_{DEB_VERSION}_amd64.deb'
    target.write_bytes(b'tampered')
    result = attempt(root, 'rejected')
    assert result.returncode != 0 and not (root / 'rejected').exists()
    print('tampered Ubuntu package rejected: PASS')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)
    (root / 'ubuntu' / 'UNEXPECTED').write_text('extra')
    result = attempt(root, 'rejected')
    assert result.returncode != 0 and not (root / 'rejected').exists()
    print('unexpected Ubuntu CI asset rejected: PASS')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)
    archive = root / 'ubuntu' / f'open-ipod-sync-{COMMIT}-source.tar'
    archive.write_bytes(b'different-source')
    manifest = root / 'ubuntu' / 'BUILD-MATERIALS.json'
    value = json.loads(manifest.read_text())
    value['source']['archive_sha256'] = digest(archive)
    manifest.write_text(json.dumps(value))
    write_checksums(root / 'ubuntu')
    result = attempt(root, 'rejected')
    assert result.returncode != 0 and not (root / 'rejected').exists()
    print('cross-platform source mismatch rejected: PASS')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)
    sbom = root / 'ubuntu' / f'ipod-sync_{DEB_VERSION}_amd64.spdx.json'
    sbom.unlink()
    sbom.symlink_to(root / 'debian' / sbom.name)
    result = attempt(root, 'rejected')
    assert result.returncode != 0 and not (root / 'rejected').exists()
    print('symlinked CI asset rejected: PASS')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    fresh(root)

    result = attempt(
        root,
        'bad-public-version',
        DEB_VERSION,
    )

    assert result.returncode != 0
    assert not (root / 'bad-public-version').exists()

    print('incorrect public version rejected: PASS')

print('dual-platform release asset tests: PASS')
