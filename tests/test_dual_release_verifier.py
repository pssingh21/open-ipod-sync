#!/usr/bin/env python3
"""Adversarial checks for the dual-platform release verifier's outer boundary."""
import hashlib
import importlib.util
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'verify-dual-release.py'
spec = importlib.util.spec_from_file_location('dual_release_verifier', SCRIPT)
assert spec is not None and spec.loader is not None
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
COMMIT = 'a' * 40
VERSION = '0.2.0-alpha.8'
SOURCE = f'open-ipod-sync-{COMMIT}-source.tar'
FILES = {
    f'ipod-sync_{VERSION}_amd64.deb',
    f'ipod-sync_{VERSION}_amd64.spdx.json',
    f'ipod-sync-ubuntu2604_{VERSION}_amd64.deb',
    f'ipod-sync-ubuntu2604_{VERSION}_amd64.spdx.json',
    SOURCE,
    'PROVENANCE.json', 'CI-SHA256SUMS', 'BUILD-MATERIALS.json',
    'TOOLCHAIN.json', 'UBUNTU2604-PROVENANCE.json',
    'UBUNTU2604-CI-SHA256SUMS', 'UBUNTU2604-BUILD-MATERIALS.json',
    'UBUNTU2604-TOOLCHAIN.json',
}


def invalid(directory):
    try:
        v.verify(directory, COMMIT)
    except ValueError:
        return
    except Exception as error:
        raise AssertionError(f'unexpected exception: {error}') from error
    raise AssertionError('unsafe release unexpectedly accepted')


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for name in FILES:
        (root / name).write_bytes(b'example')
    (root / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(b"example").hexdigest()}  {name}\n'
        for name in sorted(FILES)
    ))

    # Unsupported commit, unexpected asset and symlink all fail closed.
    try:
        v.verify(root, 'b' * 40)
    except ValueError as exc:
        assert 'commit' in str(exc)
    else:
        raise AssertionError('wrong commit accepted')

    (root / 'unexpected.txt').write_text('unexpected')
    invalid(root)
    (root / 'unexpected.txt').unlink()

    (root / 'PROVENANCE.json').unlink()
    (root / 'PROVENANCE.json').symlink_to(root / 'TOOLCHAIN.json')
    invalid(root)
    (root / 'PROVENANCE.json').unlink()
    (root / 'PROVENANCE.json').write_bytes(b'example')

    (root / 'SHA256SUMS').write_text('0' * 64 + '  PROVENANCE.json\n')
    invalid(root)
    print('dual release verifier negative boundary tests: PASS')
