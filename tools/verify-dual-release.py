#!/usr/bin/env python3
"""Fail-closed offline verification of the 14-asset dual-platform release.

Reuses the established eight-asset Debian consumer verifier unchanged.
GitHub release authenticity and attestations must be checked separately.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'docker.io/library/ubuntu@sha256:88a381d5b5eeb2b35d3ad70925a362c37ce569daf43ede89ff818ec20e4d3794'
SNAPSHOT = 'ubuntu-26.04-snapshot-20261015T000000Z'
HEX = re.compile(r'^[0-9a-f]{64}$')
SRC = re.compile(r'^open-ipod-sync-([0-9a-f]{40})-source\.tar$')
PUB = re.compile(r'^ipod-sync_([A-Za-z0-9.+~:-]+)_amd64\.deb$')
CI = re.compile(r'^ipod-sync_([A-Za-z0-9.+~:-]+)_amd64\.deb$')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def document(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'duplicate JSON key {key} in {path.name}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def checksum_set(path, expected):
    seen = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+~:-]*)', line)
        require(match is not None, f'noncanonical checksum line in {path.name}')
        checksum, name = match.groups()
        require(name not in seen, f'duplicate checksum name: {name}')
        seen[name] = checksum
    require(set(seen) == expected, f'wrong checksum file set: {path.name}')
    return seen


def verify(root, expected_commit):
    require(root.is_dir() and not root.is_symlink(), 'unsafe release directory')
    entries = list(root.iterdir())
    require(all(p.is_file() and not p.is_symlink() for p in entries), 'unsafe asset entry')
    names = {p.name for p in entries}
    require(len(names) == len(entries) == 14, 'expected exactly 14 unique regular files')
    matches = [p.name for p in entries if SRC.fullmatch(p.name)]
    debs = [p.name for p in entries if PUB.fullmatch(p.name)]
    require(len(matches) == 1 and len(debs) == 1, 'expected one source and one Debian package')
    source = matches[0]
    commit = SRC.fullmatch(source).group(1)
    require(expected_commit is None or commit == expected_commit, 'unexpected release commit')
    version = PUB.fullmatch(debs[0]).group(1)
    deb = debs[0]
    spdx = deb[:-4] + '.spdx.json'
    ub_deb = f'ipod-sync-ubuntu2604_{version}_amd64.deb'
    ub_spdx = f'ipod-sync-ubuntu2604_{version}_amd64.spdx.json'
    base_names = {deb, spdx, source, 'PROVENANCE.json', 'CI-SHA256SUMS',
                  'BUILD-MATERIALS.json', 'TOOLCHAIN.json'}
    ubuntu_names = {ub_deb, ub_spdx, 'UBUNTU2604-PROVENANCE.json',
                    'UBUNTU2604-CI-SHA256SUMS', 'UBUNTU2604-BUILD-MATERIALS.json',
                    'UBUNTU2604-TOOLCHAIN.json'}
    require(names == base_names | ubuntu_names | {'SHA256SUMS'}, 'unexpected release asset set')
    sums = checksum_set(root / 'SHA256SUMS', names - {'SHA256SUMS'})
    for name, expected in sums.items():
        require(digest(root / name) == expected, f'release checksum mismatch: {name}')
    print('Exact 14-asset checksum contract: PASS')

    # Restore an eight-asset Debian view and run the original independent
    # offline verifier, retaining its package, ELF, provenance and SBOM tests.
    with tempfile.TemporaryDirectory(prefix='dual-debian-') as d:
        view = Path(d)
        for name in base_names:
            shutil.copyfile(root / name, view / name)
        (view / 'SHA256SUMS').write_text(''.join(
            f'{sums[name]}  {name}\n' for name in sorted(base_names)))
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'verify-release.py'),
                        str(view), '--expected-commit', commit], check=True)
    print('Existing Debian deep consumer verification: PASS')

    # The published Ubuntu names are aliases. Signed provenance and CI
    # checksums retain the original ipod-sync_* filenames, unchanged.
    prov = document(root / 'UBUNTU2604-PROVENANCE.json')
    mat = document(root / 'UBUNTU2604-BUILD-MATERIALS.json')
    chain = document(root / 'UBUNTU2604-TOOLCHAIN.json')
    sbom = document(root / ub_spdx)
    debian_prov = document(root / 'PROVENANCE.json')
    original_deb = prov['subject']['name']
    require(bool(CI.fullmatch(original_deb)), 'invalid Ubuntu CI package name')
    original_spdx = original_deb[:-4] + '.spdx.json'
    require(prov['sbom']['name'] == original_spdx, 'Ubuntu CI SPDX name mismatch')
    require(prov['subject']['sha256'] == digest(root / ub_deb), 'Ubuntu provenance package digest mismatch')
    require(prov['sbom']['sha256'] == digest(root / ub_spdx), 'Ubuntu provenance SPDX digest mismatch')
    require(prov['source']['git_commit'] == commit, 'Ubuntu provenance source commit mismatch')
    require(prov['source']['repository'] == debian_prov['source']['repository'], 'cross-platform repository mismatch')
    require(prov['build']['environment'] == 'ubuntu-26.04-amd64', 'Ubuntu build environment mismatch')
    require(mat['schema'] == 'open-ipod-sync-build-materials-v1', 'Ubuntu materials schema mismatch')
    require(mat['source']['commit'] == commit, 'Ubuntu materials commit mismatch')
    require(mat['source']['archive_sha256'] == digest(root / source), 'Ubuntu materials source mismatch')
    require(mat['source']['source_date_epoch'] == prov['source']['source_date_epoch'], 'Ubuntu build epoch mismatch')
    env = mat['declared_environment']
    require(env['base_image_identity'] == IMAGE, 'Ubuntu image digest mismatch')
    require(env['snapshot_identity'] == SNAPSHOT, 'Ubuntu snapshot mismatch')
    require(mat['observed_environment']['architecture'] == 'amd64', 'Ubuntu architecture mismatch')
    require(chain['schema'] == 'open-ipod-sync-toolchain-view-v1', 'Ubuntu toolchain schema mismatch')
    require(sbom['spdxVersion'] == 'SPDX-2.3', 'Ubuntu SPDX schema mismatch')
    packages = [p for p in sbom['packages'] if p.get('SPDXID') == 'SPDXRef-Package-ipod-sync']
    require(len(packages) == 1, 'Ubuntu SPDX root package mismatch')
    package = packages[0]
    require(package['packageFileName'] == original_deb, 'Ubuntu SPDX original package identity mismatch')
    require(package['versionInfo'] == prov['package']['version'], 'Ubuntu SPDX version mismatch')
    require(any(c.get('algorithm') == 'SHA256' and c.get('checksumValue') == digest(root / ub_deb)
                for c in package['checksums']), 'Ubuntu SPDX package hash mismatch')
    require(prov['package']['name'] == 'ipod-sync' and prov['package']['architecture'] == 'amd64',
            'Ubuntu provenance package identity mismatch')
    for field, expected in (('Package', 'ipod-sync'),
                            ('Version', prov['package']['version']),
                            ('Architecture', 'amd64')):
        actual = subprocess.check_output(['dpkg-deb', '-f', str(root / ub_deb), field], text=True).strip()
        require(actual == expected, f'Ubuntu .deb {field} mismatch')
    ci_map = {original_deb: ub_deb, original_spdx: ub_spdx,
              source: source, 'PROVENANCE.json': 'UBUNTU2604-PROVENANCE.json',
              'BUILD-MATERIALS.json': 'UBUNTU2604-BUILD-MATERIALS.json',
              'TOOLCHAIN.json': 'UBUNTU2604-TOOLCHAIN.json'}
    ci_sums = checksum_set(root / 'UBUNTU2604-CI-SHA256SUMS', set(ci_map))
    for name, alias in ci_map.items():
        require(ci_sums[name] == digest(root / alias), f'Ubuntu signed CI digest mismatch: {name}')
    print('Ubuntu provenance, SBOM, material and CI identity checks: PASS')
    print('Offline dual-platform release verification: PASS')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('release_dir', type=Path)
    ap.add_argument('--expected-commit')
    args = ap.parse_args()
    try:
        verify(args.release_dir, args.expected_commit)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as err:
        ap.exit(1, f'ERROR: {err}\n')


if __name__ == '__main__':
    main()
