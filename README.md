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
0.2.0-alpha.7
```

This software is **experimental**.

Alpha.6 focuses on read-only diagnostics and automation, temporary-file
hardening, and release supply-chain integrity. It adds machine-readable
`plan --json`, improved `doctor` diagnostics, reproducible SPDX 2.3 SBOM and
provenance metadata, and GitHub/Sigstore-backed artifact attestations. The
synchronization scope remains generic incremental ADD-only.

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
`0.2.0-alpha.7` release artifact itself. Treat this release as an alpha.

## Tested platform

Validated device configuration:

- Debian 11 amd64
- iPod touch 2nd generation
- iOS 4.2.1

CI additionally performs source-build and package-audit compatibility testing on:

- Ubuntu 24.04 amd64
- Ubuntu 26.04 amd64

Those Ubuntu jobs validate that the public source tree, bundled modified
libgpod, native helpers, and Debian package can be built and audited on the
newer host library/toolchain stacks. They also install, reinstall, and remove
the package built on that same Ubuntu host to exercise package lifecycle and
host-specific shared-library dependency generation.

They do not represent real-device testing on Ubuntu and do not assert that the
Debian-11-built release package is directly installable on those
distributions. Binary packages remain tied to the ABI/library versions of the
host on which they were built.

Other host distributions and Apple devices remain experimental.

The prebuilt Debian package is intended for the environment against which it
was built. For other distributions or newer library stacks, building from
source is recommended.


## Step-by-step: download, build, install, and use

The safest normal workflow is:

```text
install or build package
        |
        v
configure a kernel-read-only music source
        |
        v
configure the iPod ifuse mount point
        |
        v
connect iPod
        |
        v
ipod-sync mount-ro
        |
        v
ipod-sync doctor
        |
        v
ipod-sync plan
        |
        v
review the plan
        |
        v
ipod-sync sync --apply
        |
        v
validation + return to read-only state
```

Planning and diagnostics are read-only. `sync --apply` is the explicit
write-capable operation.

### Option A: install the published release

The published Debian package is the canonical Debian 11 amd64 release
artifact.

With the GitHub CLI installed, download all release assets into a new
directory:

```bash
mkdir -p open-ipod-sync-alpha7
gh release download v0.2.0-alpha.7 \
  --repo pssingh21/open-ipod-sync \
  --dir open-ipod-sync-alpha7

cd open-ipod-sync-alpha7
```

Verify the downloaded release files:

```bash
sha256sum -c SHA256SUMS
```

The release itself and its individual assets can also be verified through the
GitHub CLI:

```bash
gh release verify v0.2.0-alpha.7 \
  --repo pssingh21/open-ipod-sync

gh release verify-asset \
  v0.2.0-alpha.7 \
  ./ipod-sync_0.2.0.alpha7_amd64.deb \
  --repo pssingh21/open-ipod-sync
```

Install the package:

```bash
sudo apt install ./ipod-sync_0.2.0.alpha7_amd64.deb
```

Then verify the installed command:

```bash
ipod-sync version
ipod-sync doctor
```

The published `.deb` is built in the pinned Debian 11 release environment.
Do not assume that one Debian-built binary package is portable to every newer
distribution merely because the source builds there.

### Option B: build a package from source

Building on the target host is the preferred approach when testing a newer
supported CI host such as Ubuntu 24.04 or Ubuntu 26.04.

Clone the repository with the GitHub CLI:

```bash
gh repo clone pssingh21/open-ipod-sync
cd open-ipod-sync
```

Install the source-build dependencies on Debian/Ubuntu:

```bash
sudo apt update

sudo apt install \
  ca-certificates \
  git \
  bash \
  python3 \
  build-essential \
  dpkg-dev \
  pkg-config \
  intltool \
  gettext \
  libglib2.0-dev \
  libsqlite3-dev \
  libimobiledevice-dev \
  libplist-dev \
  libxml2-dev \
  zlib1g-dev \
  libusb-1.0-0-dev \
  file
```

Build the Debian package:

```bash
./build-deb.sh
```

The package is written below `dist/`.

Inspect the result:

```bash
find dist \
  -maxdepth 1 \
  -type f \
  -name 'ipod-sync_*_amd64.deb' \
  -print
```

Audit it with the same package audit used by CI:

```bash
DEB="$(
  find dist \
    -maxdepth 1 \
    -type f \
    -name 'ipod-sync_*_amd64.deb' \
    -print \
    -quit
)"

./tools/audit-deb.sh "$DEB"
```

Then install that host-built package:

```bash
sudo apt install "$DEB"
```

The build derives ELF runtime dependencies from the actual binaries with
`dpkg-shlibdeps`, so a host-built package can use the runtime package names
appropriate for that distribution.

### Configure the music source

`open-ipod-sync` requires the configured music source path itself to be a
dedicated filesystem mount that is kernel-mounted read-only.

The tool must not be pointed directly at an ordinary writable music directory.

#### Local music directory

Suppose the real music library is:

```text
$HOME/Music
```

Create a dedicated mount point:

```bash
sudo mkdir -p /mnt/ipod-sync-music
```

Create a bind-mounted view of the library:

```bash
sudo mount --bind \
  "$HOME/Music" \
  /mnt/ipod-sync-music
```

Remount that view read-only:

```bash
sudo mount \
  -o remount,bind,ro \
  /mnt/ipod-sync-music
```

Verify the mount:

```bash
findmnt \
  -T /mnt/ipod-sync-music \
  -o TARGET,SOURCE,FSTYPE,OPTIONS
```

The `OPTIONS` column must include:

```text
ro
```

The original library path may still be writable by the user. That is fine.
The important safety boundary is that the path configured as
`IPOD_SYNC_SOURCE` is the dedicated kernel-read-only view.

#### NAS music directory

If the NAS share is already mounted read-only, it can be used directly.

For example:

```bash
findmnt \
  -T /mnt/nas-music \
  -o TARGET,SOURCE,FSTYPE,OPTIONS
```

Again, confirm that the active mount options contain `ro`.

Do not rely only on ordinary Unix file permissions such as `chmod`. The
project expects a read-only filesystem/mount boundary.

### Nested source directories are supported

The source scanner is recursive. Music does not have to live directly in the
top level of `IPOD_SYNC_SOURCE`.

For example, all of these can live below one configured source root:

```text
/mnt/ipod-sync-music/
├── Artist A/
│   ├── Album 1/
│   │   ├── Track 01.mp3
│   │   └── Track 02.mp3
│   └── singles/
│       └── New Song.mp3
├── imports/
│   └── 2026/
│       └── old-library/
│           └── Song.wma
└── misc/
    └── Another Song.mp3
```

You do not need to flatten the directory tree before planning or syncing.

Nested directory names are source organization only; they are not currently
turned into artist or album metadata on the iPod.

### Configure `ipod-sync`

The package configuration is:

```text
/etc/ipod-sync/config.env
```

Edit it:

```bash
sudoedit /etc/ipod-sync/config.env
```

A typical configuration is:

```bash
IPOD_SYNC_SOURCE=/mnt/ipod-sync-music
IPOD_SYNC_MOUNT=$HOME/ipod
```

For a read-only NAS source it might instead be:

```bash
IPOD_SYNC_SOURCE=/mnt/nas-music
IPOD_SYNC_MOUNT=$HOME/ipod
```

Create the local ifuse mount-point directory:

```bash
mkdir -p "$HOME/ipod"
```

The package lifecycle preserves an existing configuration file during
reinstallation/upgrades.

### Find the configured iPod mount point

The iPod is mounted through `ifuse`. The path is controlled by
`IPOD_SYNC_MOUNT`.

To see the configured values:

```bash
cat /etc/ipod-sync/config.env
```

Or load the configuration and print only the configured iPod path:

```bash
set -a
. /etc/ipod-sync/config.env
set +a

printf 'iPod mount point: %s\n' "$IPOD_SYNC_MOUNT"
```

After the iPod has been mounted, inspect the actual active mount:

```bash
findmnt \
  -T "$IPOD_SYNC_MOUNT" \
  -o TARGET,SOURCE,FSTYPE,OPTIONS
```

You can also inspect active ifuse/FUSE mounts:

```bash
findmnt -t fuse.ifuse,fuse
```

The normal `open-ipod-sync` operating state is read-only.

### Connect and mount the iPod read-only

Connect the iPod over USB.

Optional USB/device checks:

```bash
lsusb | grep -i -E 'apple|ipod' || true
idevice_id -l || true
```

Mount through the project in read-only mode:

```bash
ipod-sync mount-ro
```

Confirm the configured mount:

```bash
set -a
. /etc/ipod-sync/config.env
set +a

findmnt \
  -T "$IPOD_SYNC_MOUNT" \
  -o TARGET,SOURCE,FSTYPE,OPTIONS
```

### Run diagnostics before planning

Run:

```bash
ipod-sync doctor
```

`doctor` checks the important operating conditions, including packaged
components, runtime dependencies, source safety, iPod connection/mount state,
and recovery state.

Do not proceed to a write if `doctor` reports a safety failure that has not
been understood.

### Preview the synchronization plan

Human-readable plan:

```bash
ipod-sync plan
```

Machine-readable plan:

```bash
ipod-sync plan --json
```

To save a JSON plan for inspection:

```bash
ipod-sync plan --json > plan.json
```

Planning is read-only.

Review the ADD count, required media bytes, destination information, conflicts,
skips, and safety state before applying anything.

### Apply the plan

The current proven synchronization behavior is incremental **ADD-only**.

The explicit write-capable command is:

```bash
ipod-sync sync --apply
```

During an apply transaction the tool performs its preflight checks, durable
recovery-journal handling, the temporary writable iPod phase, source
revalidation, media/database commit, readback validation, and read-only
restoration.

`--apply` should only be used after reviewing the current plan.

### Recovery inspection

If an interrupted transaction left recovery state, inspect it read-only first:

```bash
ipod-sync sync --recover-check
```

This inspection path does not perform recovery writes.

Actual recovery is explicit:

```bash
ipod-sync sync --recover
```

Do not clear or edit recovery state manually.

### Unmount the iPod

When finished:

```bash
ipod-sync unmount
```

If the device is still mounted, confirm its final state with:

```bash
findmnt -T "$IPOD_SYNC_MOUNT"
```

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

## Metadata behavior

The current ADD-only path intentionally uses a simple metadata model.

For newly managed tracks:

| Value on the iPod | Current behavior |
| --- | --- |
| Title | Source filename without its extension |
| Artist | Left blank |
| Album | Left blank |
| Album artist | Left blank |
| Source folders | Used only to organize the source tree |
| Existing-track metadata | Not rewritten by the current ADD-only path |

For example:

```text
/mnt/ipod-sync-music/
└── Artist Name/
    └── Album Name/
        └── My Song.mp3
```

currently produces a managed track whose title is:

```text
My Song
```

The directory names `Artist Name` and `Album Name` do **not** automatically
become Artist and Album fields.

Likewise, the current synchronization path should not be treated as a general
embedded-tag importer. Do not assume that ID3 or other source tags will be
copied to the iPod unless that behavior is explicitly added and documented in
a future release.

This is intentional: the currently proven write surface concentrates on
safely adding playable media and committing the required Apple databases.

Existing unmanaged tracks are preserved by the ADD-only synchronization model;
the tool does not use the current feature set to rewrite their metadata.

Metadata synchronization for existing tracks, richer tag import, playlist
management, generic rename synchronization, and delete synchronization are
outside the current supported write scope.

## Install a release package

On the currently tested Debian 11 amd64 environment:

```bash
sudo apt install ./ipod-sync_0.2.0.alpha7_amd64.deb
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

For machine-readable automation, request the same dry-run plan as JSON:

```bash
ipod-sync plan --json
```

JSON mode writes only the JSON document to stdout. Planning remains read-only
with respect to the configured source filesystem and iPod; as with the normal
planner, temporary candidate files may be staged under the local ipod-sync
state directory.

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

CI package artifacts also include:

- an SPDX 2.3 JSON SBOM for the Debian package;
- a deterministic `PROVENANCE.json` document binding the Debian artifact,
  source commit, `SOURCE_DATE_EPOCH`, bundled libgpod patch, and packaged
  component hashes;
- a `SHA256SUMS` file covering the Debian package, SBOM, and provenance.

The project `PROVENANCE.json` document is deterministic build metadata. It is
not itself a cryptographically signed SLSA/in-toto attestation.

After all package, reproducibility, and lifecycle gates pass on a push to
`main`, GitHub Actions additionally creates cryptographically signed artifact
attestations using GitHub's Sigstore-backed attestation service:

- SLSA build-provenance attestations cover the Debian package, SPDX SBOM,
  `PROVENANCE.json`, and `SHA256SUMS`;
- an SPDX 2.3 SBOM attestation binds the generated SBOM to the Debian package.

The attestations are associated with this GitHub repository and can be verified
against downloaded artifacts with the GitHub CLI.

Verify SLSA build provenance:

```bash
gh attestation verify ./ipod-sync_0.2.0.alpha7_amd64.deb \
  --repo pssingh21/open-ipod-sync
```

The same command can be used for the downloaded `.spdx.json`,
`PROVENANCE.json`, and `SHA256SUMS` artifacts.

Verify the SPDX 2.3 SBOM attestation attached to the Debian package:

```bash
gh attestation verify ./ipod-sync_0.2.0.alpha7_amd64.deb \
  --repo pssingh21/open-ipod-sync \
  --predicate-type https://spdx.dev/Document/v2.3
```

Artifact attestations are generated only by successful `main`-branch CI builds;
pull-request workflows do not receive the attestation-signing permissions.

## Known limitations

- ADD-only synchronization.
- No deletion synchronization.
- No rename synchronization.
- No metadata synchronization for existing tracks.
- Artwork support is disabled in the bundled libgpod build.
- Device compatibility outside the tested iPod touch 2G / iOS 4.2.1 combination
  is not yet established.
- The current prebuilt package targets Debian 11 amd64.
- The bundled libgpod code is legacy software and may require additional
  hardening beyond the changes maintained here.

## Contributing

This is an early reverse-engineering and interoperability project.

Before submitting changes:

```bash
./tools/public-sanity-check.sh
```

must pass.

Changes affecting device writes should be tested especially carefully and should
preserve the fail-closed transaction model.

## CI, privacy, reproducibility, and verifiable releases

The public project is designed so that a release can be checked beyond simply
"the build passed".

### Safety regression coverage

The public test suite exercises the safety-critical behavior using synthetic
temporary source/device trees, so CI does not require access to a real iPod or
private music library.

Coverage includes:

- content-SHA-256 planning;
- duplicate-content multiplicity;
- destination allocation;
- planner fail-closed behavior;
- source revalidation;
- destination collisions;
- media-copy verification;
- live database-preimage drift;
- rollback snapshot integrity;
- transaction ordering;
- recovery state-machine behavior;
- read-only recovery inspection;
- CLI routing for dry-run, `--apply`, `--recover`, and `--recover-check`;
- conflicting/unsafe CLI combinations;
- active recovery-journal blocking;
- JSON planner output;
- package lifecycle behavior.

### Public-source and privacy checks

CI runs the public-source sanity suite before release artifacts are accepted.

The source/package audits are intended to catch accidental leakage from the
development environment, including privacy-sensitive local path/fingerprint
material that should not become part of the public source or binary package.

Package auditing also checks important release invariants such as:

- expected package identity/version;
- payload ownership;
- runtime linkage;
- packaged component layout;
- absence of Python bytecode/cache artifacts;
- privacy fingerprints;
- installed application version;
- package configuration behavior.

Generated local `build/` and `dist/` output is not treated as source.

### Canonical Debian 11 release build

Debian 11 amd64 is the canonical release-build environment.

CI pins:

- the Debian 11 container image by digest;
- the Debian package repository snapshot used for the build;
- GitHub Actions dependencies by immutable commit SHA.

This reduces environmental drift between builds.

### Reproducible builds

The release build normalizes timestamps using `SOURCE_DATE_EPOCH` and removes
unnecessary nondeterministic build output such as Python bytecode.

The reproducibility gate performs independent builds and requires the generated
release material to compare byte-for-byte.

The reproducibility scope includes:

- Debian package;
- SPDX SBOM;
- `PROVENANCE.json`;
- CI `SHA256SUMS`.

A release is therefore not accepted merely because two builds are
functionally similar: the reproducibility gate expects identical bytes.

### Ubuntu host compatibility

CI also builds and audits the source on:

```text
Ubuntu 24.04 amd64
Ubuntu 26.04 amd64
```

Those jobs validate:

- public-source sanity;
- native/source compilation;
- modern `libplist` pkg-config compatibility;
- host-specific ELF dependency generation;
- Debian package audit;
- install/reinstall/remove package lifecycle.

Runtime library dependencies are derived from the packaged ELF binaries with
`dpkg-shlibdeps`. This allows each build host to resolve the SONAME
requirements to its own distribution package names.

These jobs prove host-build/package compatibility. They do **not** claim
real-device validation on Ubuntu.

### SPDX software bill of materials

The audited Debian artifact has a deterministic SPDX 2.3 JSON SBOM.

The SBOM is part of the CI/reproducibility/release verification chain rather
than an independently generated afterthought.

### Provenance metadata

CI generates deterministic `PROVENANCE.json` metadata that binds release
material to relevant build/source identity, including the source commit and
selected packaged component information.

The release workflow verifies that the provenance belongs to the exact commit
being released.

### GitHub/Sigstore artifact attestations

After the build, a dedicated post-gate job creates GitHub-backed attestations.

The attested material includes:

- Debian package;
- SPDX document;
- `PROVENANCE.json`;
- CI `SHA256SUMS`.

The Debian package also receives an SPDX 2.3 SBOM attestation bound directly
to that package.

The attestation job runs only after the required package, reproducibility, and
lifecycle gates succeed.

### Exact-CI-byte release publication

The automated Release workflow does **not** rebuild the Debian package.

For a release it:

1. identifies the exact successful normal-CI run for the current `main` SHA;
2. downloads the artifacts already produced and tested by that run;
3. verifies the CI checksum manifest;
4. verifies the existing SLSA/SPDX attestations;
5. copies/renames those same bytes into the public release bundle;
6. creates the release-specific checksum manifest;
7. requires approval through the protected `release` Environment;
8. creates an annotated tag for the exact source commit;
9. publishes the prerelease.

This maintains the invariant:

> The bytes published to users are the bytes that passed the release CI gates.

### Immutable releases

Repository releases are published with GitHub immutable releases enabled.

The release workflow refuses to proceed when the intended tag or GitHub
Release already exists and never uses asset clobbering as a repair mechanism.

Once an immutable release has been published, the expected remediation for a
release defect is a new version, not replacement of the historical assets.

### Post-publication verification

Publication itself is not considered the end of the workflow.

After publishing, CI downloads the public assets again and verifies:

- release `SHA256SUMS`;
- GitHub signed release attestation;
- each individual release asset against the release attestation;
- Debian SLSA provenance;
- Debian SPDX attestation;
- SPDX-document provenance;
- `PROVENANCE.json` provenance;
- CI-manifest provenance.

A successful automated release ends only after this fresh-download
verification passes.

### What the verification does not mean

Reproducibility, package lifecycle tests, SBOMs, and attestations establish
build and supply-chain properties. They do not magically expand device
compatibility.

The real-device validation boundary remains the explicitly documented legacy
iPod configuration. See
[Architecture and transaction safety model](docs/ARCHITECTURE.md) for that
boundary and the synchronization safety model.

## Project documentation

- [Architecture and transaction safety model](docs/ARCHITECTURE.md)
- [Release runbook](docs/RELEASE-RUNBOOK.md)

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
