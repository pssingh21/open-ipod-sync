# open-ipod-sync

`open-ipod-sync` is an experimental, fail-closed, **ADD-only** open-source music synchronizer for legacy iPod touch devices on Linux.

It was developed and validated with an **iPod touch 2nd generation running iOS 4.2.1** and a Debian 11 amd64 host.

The GitHub project is named **open-ipod-sync**. The command-line program and
Debian package remain named `ipod-sync`.

The project can:

- discover songs from a read-only source filesystem;
- compare source files against music already present on the iPod using content hashes;
- add only genuinely new tracks;
- transcode unsupported source formats such as WMA to MP3 with FFmpeg;
- update the legacy Apple music databases;
- generate the required Hash72-compatible signature;
- perform database changes inside an iTunes-style synchronization envelope;
- verify copied media by SHA-256 readback;
- roll back failed transactions;
- leave the iPod mounted read-only outside explicitly authorized write transactions.

## Status

Current release:

```text
0.2.0-alpha.5
```

This software is **experimental**.

Alpha.5 is primarily a safety, reproducibility, CI, package-validation, and
recovery-hardening update. It adds automated package auditing, byte-for-byte
reproducibility verification, package lifecycle testing, synthetic planner and
transaction regression coverage, recovery-state-machine coverage, and
fail-closed validation of transaction journal phases.

The synchronization scope remains generic incremental ADD-only.

The generic incremental ADD path has been live-tested end-to-end during development, including:

- new-track detection;
- WMA to MP3 conversion;
- native synchronization envelope;
- signed database commit;
- full media SHA-256 readback;
- post-commit database validation;
- physical playback on the iPod.

The public `0.2.0-alpha.3` predecessor additionally passed:

- source privacy checks;
- package privacy checks;
- package ownership checks;
- clean rebuild of the bundled modified libgpod;
- upgrade from the previously validated `0.1.6` package;
- configuration preservation;
- runtime `doctor` checks;
- real-device read-only/idempotency planning.

A fresh live ADD transaction has not yet been performed with the exact
`0.2.0-alpha.5` release artifact itself. Treat this release as an alpha.

## Tested platform

Validated configuration:

- Debian 11 amd64
- iPod touch 2nd generation
- iOS 4.2.1

Other Debian/Ubuntu versions and other Apple devices are currently experimental.

The prebuilt Debian package is intended for the environment against which it was
built. For other distributions or newer library stacks, building from source is
recommended.

## Safety model

`ipod-sync` is deliberately conservative.

### Music source

The configured music source must be a **dedicated filesystem mountpoint** that
the Linux kernel reports as read-only.

For example:

```text
IPOD_SYNC_SOURCE=/mnt/music
```

The application refuses to continue if the source write barrier is not satisfied.

It does not intentionally rename, delete, modify, chmod, or transcode files in
the source filesystem.

### iPod

The iPod should normally be mounted read-only.

Read-only operations such as:

```bash
ipod-sync doctor
ipod-sync mount-ro
ipod-sync plan
ipod-sync recover-check
```

do not authorize a synchronization transaction.

A live write requires an explicit command:

```bash
ipod-sync sync --apply
```

`--apply` authorizes that execution only.

### Existing tracks

This release is ADD-only.

Existing iPod tracks are not intentionally:

- deleted;
- renamed;
- replaced;
- metadata-rewritten.

## Metadata

For newly managed tracks:

- title = source filename without extension;
- artist = blank;
- album = blank;
- album artist = blank.

This alpha requires an existing song with blank artist, album, and album-artist
metadata that can be used as an Apple sort-map template.

There is no hardcoded device-specific template identifier.

## Install a release package

On the currently tested Debian 11 amd64 environment:

```bash
sudo apt install ./ipod-sync_0.2.0~alpha5_amd64.deb
```

Then edit:

```text
/etc/ipod-sync/config.env
```

Example:

```bash
IPOD_SYNC_SOURCE=/mnt/music
IPOD_SYNC_MOUNT=$HOME/ipod
```

The source path must itself be the dedicated read-only mountpoint.

Verify the installation:

```bash
ipod-sync version
ipod-sync doctor
```

Mount the iPod read-only if required:

```bash
ipod-sync mount-ro
```

Preview synchronization:

```bash
ipod-sync plan
```

Only after reviewing the plan should a live transaction be explicitly requested:

```bash
ipod-sync sync --apply
```

## Build from source

Install the build dependencies on Debian:

```bash
sudo apt install \
  build-essential \
  dpkg-dev \
  pkg-config \
  intltool \
  gettext \
  libglib2.0-dev \
  libsqlite3-dev \
  libplist-dev \
  libxml2-dev \
  zlib1g-dev \
  libimobiledevice-dev
```

Run the public source sanity tests:

```bash
./tools/public-sanity-check.sh
```

Then build:

```bash
./build-deb.sh
```

The build recompiles the bundled modified libgpod source rather than redistributing
a development-machine copy of `libgpod.so`.

## Why a modified libgpod is included

Legacy iPod touch synchronization requires behavior that is not provided by the
stock libgpod package used during development.

The repository therefore contains:

```text
third_party/libgpod-patched-source/
third_party/libgpod-0.8.3-ipod-sync.patch
```

The patch provides a reviewable delta from the libgpod 0.8.3 base tree.

The release build compiles this source using a neutral runtime prefix and strips
development build-path information from packaged binaries.

See `THIRD_PARTY.md` and the bundled libgpod copyright/license material for
additional information.

## Repository layout

```text
src/                      Main Python synchronization implementation
src/ipodctl/              Apple database/container support
native/                   Native synchronization/signing components
tests/                    Public regression tests
tools/                    Source sanity/privacy checks
third_party/              Modified libgpod source and reviewable patch
vendor/                   Provenance and supporting source
build-deb.sh              Debian package builder
```

## Privacy and reproducibility

The public source sanity checker rejects known private-development artifacts,
compiled library objects, Python bytecode caches, and development-machine paths.

Before a release is published, both the source tree and generated package should
pass their privacy and ownership audits.

Release-specific SHA-256 checksums are published as a `SHA256SUMS` asset with
each GitHub release rather than being stored inside the tagged source tree.

## Known limitations

- ADD-only synchronization.
- No deletion synchronization.
- No rename synchronization.
- No metadata synchronization for existing tracks.
- Artwork support is disabled in the bundled libgpod build.
- Device compatibility outside the tested iPod touch 2G / iOS 4.2.1 combination
  is not yet established.
- The current prebuilt package targets Debian 11 amd64.
- Legacy libgpod code still contains an upstream `tmpnam()` usage that should be
  replaced in a future release.

## Contributing

This is an early reverse-engineering and interoperability project.

Before submitting changes:

```bash
./tools/public-sanity-check.sh
```

must pass.

Changes affecting device writes should be tested especially carefully and should
preserve the fail-closed transaction model.

## License

This repository includes the GNU Lesser General Public License version 2.1 in
`LICENSE`.

Third-party code retains its respective copyright and licensing terms. See
`THIRD_PARTY.md` and the notices included with the corresponding source.

## Disclaimer

This project is not affiliated with or endorsed by Apple Inc.

Writing synchronization databases on legacy devices carries a risk of library
corruption or data loss. Keep backups and review synchronization plans before
authorizing writes.
