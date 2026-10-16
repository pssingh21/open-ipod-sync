#!/usr/bin/env python3
"""Stage an exact two-platform release candidate; no network or publishing.

Inputs must already have passed independent GitHub attestation verification.
CI-origin provenance and SBOM are copied unchanged; filename mapping does
not change the identity or contents of the packages.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_ci(root, deb_version, commit, environment):
    require(root.is_dir() and not root.is_symlink(), f'unsafe CI directory: {root}')
    deb = f'ipod-sync_{deb_version}_amd64.deb'
    spdx = f'ipod-sync_{deb_version}_amd64.spdx.json'
    source = f'open-ipod-sync-{commit}-source.tar'
    names = {deb, spdx, source, 'PROVENANCE.json', 'BUILD-MATERIALS.json', 'TOOLCHAIN.json', 'SHA256SUMS'}
    require({p.name for p in root.iterdir()} == names, f'{environment}: unexpected CI file set')
    for name in names:
        p = root / name
        require(p.is_file() and not p.is_symlink(), f'{environment}: unsafe file: {name}')
    entries = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\]+)', line)
        require(match is not None, f'{environment}: invalid CI checksum line')
        digest, name = match.groups()
        require(name not in entries, f'{environment}: duplicate checksum entry')
        entries[name] = digest
    require(set(entries) == names - {'SHA256SUMS'}, f'{environment}: incorrect CI checksum set')
    for name, digest in entries.items():
        require(sha(root / name) == digest, f'{environment}: checksum mismatch: {name}')

    provenance = json.loads((root / 'PROVENANCE.json').read_text())
    require(provenance['source']['git_commit'] == commit, f'{environment}: provenance commit mismatch')
    require(provenance['subject'] == {'name': deb, 'sha256': sha(root / deb)}, f'{environment}: provenance package mismatch')
    require(provenance['sbom']['name'] == spdx and provenance['sbom']['sha256'] == sha(root / spdx), f'{environment}: provenance SBOM mismatch')
    require(provenance['build']['environment'] == environment, f'{environment}: provenance environment mismatch')
    materials = json.loads((root / 'BUILD-MATERIALS.json').read_text())
    require(materials['source']['commit'] == commit and materials['source']['archive_sha256'] == sha(root / source), f'{environment}: material source mismatch')
    return {'deb': deb, 'spdx': spdx, 'source': source}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--debian-ci', required=True, type=Path)
    parser.add_argument('--ubuntu-ci', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--deb-version', required=True)
    parser.add_argument('--public-version', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    for value in (args.deb_version, args.public_version):
        require(re.fullmatch(r'[0-9A-Za-z.+~:-]+', value), 'invalid version string')
    require(re.fullmatch(r'[0-9a-f]{40}', args.commit), 'invalid commit')
    output = args.output.absolute()
    require(not output.exists() and not output.is_symlink(), 'output already exists')
    for root in (args.debian_ci.absolute(), args.ubuntu_ci.absolute()):
        require(root != output and root not in output.parents and output not in root.parents, 'overlapping input/output')
    debian = read_ci(args.debian_ci, args.deb_version, args.commit,
                     'debian-11-amd64-snapshot-20260830T235959Z')
    ubuntu = read_ci(args.ubuntu_ci, args.deb_version, args.commit, 'ubuntu-26.04-amd64')
    require(sha(args.debian_ci / debian['source']) == sha(args.ubuntu_ci / ubuntu['source']),
            'Debian and Ubuntu source archive bytes differ')
    mappings = {
        f'ipod-sync_{args.public_version}_amd64.deb': args.debian_ci / debian['deb'],
        f'ipod-sync_{args.public_version}_amd64.spdx.json': args.debian_ci / debian['spdx'],
        'PROVENANCE.json': args.debian_ci / 'PROVENANCE.json',
        'CI-SHA256SUMS': args.debian_ci / 'SHA256SUMS',
        'BUILD-MATERIALS.json': args.debian_ci / 'BUILD-MATERIALS.json',
        'TOOLCHAIN.json': args.debian_ci / 'TOOLCHAIN.json',
        debian['source']: args.debian_ci / debian['source'],
        f'ipod-sync-ubuntu2604_{args.public_version}_amd64.deb': args.ubuntu_ci / ubuntu['deb'],
        f'ipod-sync-ubuntu2604_{args.public_version}_amd64.spdx.json': args.ubuntu_ci / ubuntu['spdx'],
        'UBUNTU2604-PROVENANCE.json': args.ubuntu_ci / 'PROVENANCE.json',
        'UBUNTU2604-CI-SHA256SUMS': args.ubuntu_ci / 'SHA256SUMS',
        'UBUNTU2604-BUILD-MATERIALS.json': args.ubuntu_ci / 'BUILD-MATERIALS.json',
        'UBUNTU2604-TOOLCHAIN.json': args.ubuntu_ci / 'TOOLCHAIN.json',
    }
    require(len(mappings) == 13, 'release payload filename collision')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.dual-release-', dir=output.parent) as temp:
        staging = Path(temp) / 'assets'
        staging.mkdir()
        for name, origin in mappings.items():
            shutil.copyfile(origin, staging / name)
            require(sha(origin) == sha(staging / name), f'copy mismatch: {name}')
        (staging / 'SHA256SUMS').write_text(''.join(
            f'{sha(staging / name)}  {name}\n' for name in sorted(mappings)
        ))
        require(len(list(staging.iterdir())) == 14, 'release contract is not 14 files')
        os.rename(staging, output)
    print('Dual-platform candidate: PASS (14 assets; no publication)')


if __name__ == '__main__':
    main()
