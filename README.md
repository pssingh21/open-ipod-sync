# open-ipod-sync

`open-ipod-sync` is an experimental Linux tool for safely synchronizing music to legacy iPod touch devices.

The project is intentionally conservative. It is designed around:

- a kernel-mounted, read-only music source;
- a normally read-only iPod mount;
- dry-run planning before synchronization;
- explicit authorization before any device write;
- fail-closed validation and recovery;
- reproducible and auditable release artifacts.

The synchronization model is currently **incremental ADD-only**.

## Current release

```text
0.2.0-alpha.6
```

This software is **experimental**.

The generic incremental ADD path has been live-tested end-to-end during development, including:

- new-track detection;
- WMA-to-MP3 conversion;
- signed database generation;
- Apple synchronization-envelope handling;
- full media SHA-256 readback;
- post-commit database validation;
- physical playback on the iPod.

A fresh live ADD transaction has not yet been performed with the exact `0.2.0-alpha.6` release artifact itself. Treat this release as an alpha.

## Validated platform

Real-device validation currently covers:

- Debian 11 amd64
- iPod touch 2nd generation
- iOS 4.2.1

Other Linux distributions and Apple devices remain experimental.

CI also exercises supported source/build paths on newer environments, but that is not the same as real-device validation.

Binary Debian packages are tied to the ABI and library environment against which they were built. If your system differs significantly from the validated environment, building the package from source is recommended.

---

# Quick start

The normal workflow is:

1. install `open-ipod-sync`;
2. mount your music source read-only;
3. configure the source and iPod mount paths;
4. connect the iPod;
5. mount the iPod read-only with `ipod-sync`;
6. run diagnostics;
7. preview the synchronization plan;
8. explicitly authorize the sync only after reviewing the plan.

## 1. Install a release package

Download the Debian package for the release you want to use.

For the current validated release:

```bash
sudo apt install ./ipod-sync_0.2.0.alpha6_amd64.deb
```

Verify the installation:

```bash
ipod-sync version
```

The package installs its configuration at:

```text
/etc/ipod-sync/config.env
```

---

# Music source

The music source must itself be a **dedicated filesystem mount point that Linux reports as read-only**.

A typical configuration is:

```bash
IPOD_SYNC_SOURCE=/mnt/music
```

`open-ipod-sync` refuses to continue when the configured source does not satisfy the read-only source barrier.

The application does not intentionally rename, delete, modify, chmod, or transcode files in the source filesystem.

Any conversion required for the iPod happens outside the source filesystem.

## Nested directories are supported

Your music does not need to live in a flat directory.

For example:

```text
/mnt/music/
├── Artist A/
│   ├── Album 1/
│   │   ├── Track 01.mp3
│   │   └── Track 02.mp3
│   └── Album 2/
│       └── Track 01.wma
├── Artist B/
│   └── Track.mp3
└── Misc/
    └── More/
        └── Music/
            └── Track.mp3
```

`open-ipod-sync` scans the source recursively.

The directory configured as `IPOD_SYNC_SOURCE` must still be the dedicated read-only mount point.

---

# Using an SMB/NAS music source

A NAS is a good fit for the source library as long as the SMB share is mounted **read-only by Linux**.

The examples below use:

```text
/mnt/music
```

as the local mount point.

## Install CIFS support

On Debian or Ubuntu:

```bash
sudo apt update
sudo apt install cifs-utils
```

## Create the local mount point

```bash
sudo mkdir -p /mnt/music
```

For the strongest isolation, the NAS should expose the music collection as its own SMB share rather than mounting a broad NAS share containing unrelated writable data.

For example:

```text
//nas.example/Music
```

## Store SMB credentials safely

Do not place the NAS password directly in the mount command or in the shell history.

Create a root-readable credentials file:

```bash
sudo install -m 600 /dev/null /etc/open-ipod-sync-smb.credentials
sudoedit /etc/open-ipod-sync-smb.credentials
```

Add:

```text
username=YOUR_NAS_USERNAME
password=YOUR_NAS_PASSWORD
```

If your SMB environment requires a domain, you can also add:

```text
domain=YOUR_DOMAIN
```

## Mount the NAS read-only

Replace `nas.example` and `Music` with your NAS hostname and SMB share:

```bash
sudo mount -t cifs //nas.example/Music /mnt/music \
  -o ro,credentials=/etc/open-ipod-sync-smb.credentials,vers=3.0,uid=$(id -u),gid=$(id -g),file_mode=0444,dir_mode=0555,nosuid,nodev
```

The important option is:

```text
ro
```

That makes the SMB filesystem read-only from the Linux client's perspective.

The restrictive file and directory modes provide an additional layer of protection:

```text
file_mode=0444
dir_mode=0555
```

## Verify that it is really read-only

Run:

```bash
findmnt -no TARGET,FSTYPE,OPTIONS /mnt/music
```

The output should identify the filesystem as CIFS and contain `ro`.

For example:

```text
/mnt/music cifs ro,...
```

You can also run:

```bash
ipod-sync doctor
```

after configuration. The tool independently validates the source safety barrier before synchronization.

Do not rely only on NAS permissions. `open-ipod-sync` deliberately requires Linux itself to report the configured source filesystem as read-only.

---

# Configure open-ipod-sync

Edit:

```bash
sudoedit /etc/ipod-sync/config.env
```

A typical configuration is:

```bash
IPOD_SYNC_SOURCE=/mnt/music
IPOD_SYNC_MOUNT=$HOME/ipod
```

`IPOD_SYNC_SOURCE` is your dedicated read-only music mount.

`IPOD_SYNC_MOUNT` is where `open-ipod-sync` should mount the iPod.

---

# Connecting and mounting the iPod

Connect the iPod by USB and make sure it is unlocked and trusted by the computer if required.

You **do not need to find where your desktop environment mounted the iPod**.

In particular, you do not need to discover paths such as:

```text
/run/user/1000/gvfs/afc:host=...
```

or:

```text
/media/$USER/...
```

Those are desktop- or operating-system-managed mount locations and are not needed for the normal `open-ipod-sync` workflow.

Instead, `open-ipod-sync` uses the path configured by:

```bash
IPOD_SYNC_MOUNT=$HOME/ipod
```

`$HOME/ipod` is not a universal automatic Linux iPod mount location. It is simply a predictable mount point chosen for `open-ipod-sync`.

Mount the connected iPod read-only with:

```bash
ipod-sync mount-ro
```

The tool uses `ifuse` and mounts the device at the configured `IPOD_SYNC_MOUNT`.


### ifuse 1.2.0 safety requirement

Do **not** use upstream `ifuse` 1.2.0 with `open-ipod-sync`.

Upstream identifies 1.2.0 as having a serious data-corruption bug in its FUSE
initialization behavior. The defect is fixed in `ifuse` 1.2.1.
`open-ipod-sync` therefore refuses to mount through or trust a device mounted
with `ifuse` 1.2.0.

At the time this guard was introduced, Ubuntu 26.04 (Resolute) provides
`ifuse` `1.2.0-2` from the Ubuntu archive. Ubuntu 24.04 uses the older
1.1.4 line and is not affected by this specific regression.

Check the active version before mounting an iPod:

```bash
command -v ifuse
ifuse --version
dpkg-query -W -f='${Version}\n' ifuse
```

If the active version is 1.2.0, do not run `plan` or `sync` through that mount.
Unmount an existing iPod mount first:

```bash
ipod-sync unmount
```

On Ubuntu 26.04, until the Ubuntu archive supplies a fixed `ifuse`, install
upstream 1.2.1 under `/usr/local`:

```bash
sudo apt update

sudo apt install \
  build-essential \
  pkg-config \
  git \
  autoconf \
  automake \
  libtool-bin \
  libplist-dev \
  libimobiledevice-dev \
  libfuse3-dev \
  usbmuxd

work="$(mktemp -d)"

git clone \
  --depth 1 \
  --branch 1.2.1 \
  https://github.com/libimobiledevice/ifuse.git \
  "$work/ifuse"

cd "$work/ifuse"

test "$(git rev-parse --short=7 HEAD)" = "f7eac74"

./autogen.sh --prefix=/usr/local
make -j"$(nproc)"
sudo make install
sudo ldconfig

hash -r

command -v ifuse
ifuse --version
```

The active binary should resolve to `/usr/local/bin/ifuse` and report version
1.2.1. The Ubuntu `ifuse` package may remain installed to satisfy normal Debian
package dependency resolution; the safe `/usr/local/bin/ifuse` takes precedence
in the normal shell `PATH`.

Then verify readiness:

```bash
ipod-sync doctor
```

If Ubuntu later ships `ifuse` 1.2.1 or newer, the manual `/usr/local`
installation is no longer required for this specific issue.

Upstream references:

- <https://github.com/libimobiledevice/ifuse>
- <https://github.com/libimobiledevice/ifuse/releases/tag/1.2.1>

Ubuntu 26.04 package reference:

- <https://packages.ubuntu.com/resolute/amd64/utils/ifuse>

Verify it with:

```bash
findmnt "$HOME/ipod"
```

or simply run:

```bash
ipod-sync doctor
```

When finished, unmount it with:

```bash
ipod-sync unmount
```

---

# Check the environment

Before planning or synchronizing, run:

```bash
ipod-sync doctor
```

`doctor` performs read-only diagnostics covering:

- required runtime dependencies;
- packaged components;
- source mount safety;
- iPod mount state;
- connected-device state;
- recovery state;
- overall readiness.

`doctor` does not authorize a device-write transaction.

---

# Preview synchronization

Always inspect a dry-run plan before performing a write:

```bash
ipod-sync plan
```

The plan does not modify the iPod.

For automation or programmatic inspection:

```bash
ipod-sync plan --json
```

The JSON form provides a machine-readable synchronization plan including planned additions and relevant safety information.

If the source and iPod are already synchronized, the plan reports that there is nothing to add.

---

# Perform synchronization

A live synchronization requires explicit authorization:

```bash
ipod-sync sync --apply
```

The `--apply` flag authorizes writes for that execution only.

Without explicit authorization, synchronization writes are refused.

During a successful transaction, `open-ipod-sync` performs its validation, media-copy, database-generation, commit, and post-write verification workflow and returns the iPod to read-only state afterward.

Do not disconnect the iPod during an active write transaction.

---

# Recovery

If a previous synchronization was interrupted, inspect the state without writing:

```bash
ipod-sync recover-check
```

If recovery is required:

```bash
ipod-sync recover
```

The recovery implementation is fail-closed. An ambiguous or unproven transaction state is not silently treated as successful.

See:

```text
docs/RELEASE-RUNBOOK.md
```

for the detailed operational and recovery procedure.

---

# Metadata behavior

For newly managed tracks, the current alpha intentionally uses simple metadata:

- **title** — source filename without its extension;
- **artist** — blank;
- **album** — blank;
- **album artist** — blank.

For example:

```text
/mnt/music/Moby/Play/Porcelain.mp3
```

becomes a track whose title is:

```text
Porcelain
```

The parent directories are used for locating files in the source tree; they are not automatically interpreted as artist or album metadata.

The current alpha requires a suitable existing blank-metadata track on the iPod for the Apple sort-map template used by the database writer.

There is no hard-coded device-specific template identifier.

---

# Existing tracks and current limitations

The current synchronization model is **ADD-only**.

Existing iPod tracks are not intentionally:

- deleted;
- renamed;
- replaced;
- metadata-rewritten.

Current limitations include:

- no delete synchronization;
- no rename synchronization;
- no metadata updates for existing tracks;
- artwork support is disabled;
- device support remains intentionally narrow;
- this remains experimental software.

---

# Command reference

```bash
ipod-sync version
ipod-sync doctor
ipod-sync mount-ro
ipod-sync unmount
ipod-sync plan
ipod-sync plan --json
ipod-sync sync --apply
ipod-sync recover-check
ipod-sync recover
```

Typical session:

```bash
ipod-sync mount-ro
ipod-sync doctor
ipod-sync plan

# Review the plan carefully.

ipod-sync sync --apply

ipod-sync unmount
```

---

# Build from source

You do not need to build from source when using a compatible prebuilt release package.

Build from source when:

- your Linux environment differs from the validated package environment;
- you are developing `open-ipod-sync`;
- you want to independently reproduce the package.

## Clone the repository

```bash
git clone https://github.com/pssingh21/open-ipod-sync.git
cd open-ipod-sync
```

## Install build dependencies

On Debian/Ubuntu:

```bash
sudo apt update

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

Runtime dependencies are declared by the generated Debian package.

## Run the public sanity checks

Before building:

```bash
./tools/public-sanity-check.sh
```

## Build the Debian package

```bash
./build-deb.sh
```

The generated artifacts are placed under:

```text
dist/
```

Install the resulting package with:

```bash
sudo apt install ./dist/ipod-sync_*.deb
```

Then configure:

```text
/etc/ipod-sync/config.env
```

There is no separate second installation procedure after this point. Continue with the normal setup described earlier in this README.

---

# Safety model

The project applies multiple independent safety barriers.

## Source filesystem

The configured music source must be a dedicated filesystem mount point reported read-only by the Linux kernel.

Source writes are forbidden.

The program does not intentionally modify the source during:

- scanning;
- hashing;
- planning;
- conversion;
- candidate construction;
- synchronization;
- rollback;
- recovery.

## iPod filesystem

The iPod remains read-only during normal inspection and planning.

Read-only operations include:

```bash
ipod-sync doctor
ipod-sync mount-ro
ipod-sync plan
ipod-sync plan --json
ipod-sync recover-check
```

A writable device state is entered only as part of an explicitly authorized transaction or recovery operation and is restored to read-only afterward.

## Transactions

Synchronization uses a persistent transaction journal and validated preimages.

The implementation checks for conditions such as:

- source changes after planning;
- destination collisions;
- device-state drift;
- copied-media hash mismatch;
- database validation failure;
- incomplete transaction state.

Failures are handled fail-closed.

---

# Privacy, reproducibility, and release integrity

`open-ipod-sync` is designed so public source and release artifacts can be independently inspected.

## Privacy

Public-source and package audits check for known development-machine and private-environment fingerprints.

Release artifacts are checked to avoid unintentionally publishing items such as:

- developer home-directory paths;
- private NAS addresses;
- private usernames;
- test-environment paths;
- temporary development artifacts;
- Python bytecode and cache files.

Your music library is processed locally by the synchronization tool. The synchronization path does not require uploading the music collection to a remote service.


### Artifact privacy boundary

Public artifacts are scanned with `tools/privacy-scan.py` before they are
uploaded or published.

The same canonical scanner is used for:

- the checked-out public source tree;
- generated Debian packages, including package payload and control metadata;
- SPDX SBOM and provenance files;
- checksum manifests and checksum sidecars;
- CI artifact bundles;
- release bundles before publication;
- freshly downloaded published release assets;
- supported tar and ZIP archives, including their member contents.

The scanner rejects known private-development fingerprints, developer home
paths, RFC1918 private IP addresses, common credential/token formats, private
key material, Apple pairing/private-key material, and contextual device
identifiers.

Scanning is fail-closed: an unreadable or uninspectable supported artifact
causes the privacy gate to fail rather than silently skipping it.

Filesystem symlinks are not followed. Their names and targets are inspected as
data, so privacy scanning cannot escape through a symlink into another
filesystem such as the configured NAS source.

The source music tree remains strictly read-only. Privacy scanning only reads
source/public artifacts and never renames, deletes, chmods, stages into, or
otherwise modifies the configured source filesystem.

Generated checksum sidecars are also required to contain artifact basenames
only. This prevents checkout paths such as developer home directories from
being embedded in otherwise public build metadata.

## Reproducible builds

The Debian build uses deterministic build inputs and normalized timestamps.

CI independently rebuilds the package and requires the resulting package to match byte-for-byte.

Release metadata also records the source and artifact relationship.

## Package auditing

CI validates properties including:

- package version consistency;
- package ownership;
- expected runtime linkage;
- absence of unwanted bytecode/cache files;
- stripped packaged ELF binaries;
- privacy fingerprints;
- package install and upgrade behavior;
- configuration preservation.

## Supply-chain metadata

CI generates:

- an SPDX 2.3 JSON SBOM;
- `PROVENANCE.json`;
- SHA-256 checksums.

The provenance metadata binds release artifacts to information including:

- the source commit;
- `SOURCE_DATE_EPOCH`;
- Debian package hash;
- SBOM hash;
- bundled modified-libgpod patch;
- selected packaged-component hashes.

## GitHub artifact attestations

Post-gate builds on `main` produce GitHub/Sigstore-backed attestations.

SLSA build provenance can be verified with:

```bash
gh attestation verify ./ipod-sync_0.2.0.alpha6_amd64.deb \
  --repo pssingh21/open-ipod-sync
```

The downloaded SPDX and provenance artifacts can be verified in the same way.

The SPDX 2.3 attestation attached to the Debian package can be checked with:

```bash
gh attestation verify ./ipod-sync_0.2.0.alpha6_amd64.deb \
  --repo pssingh21/open-ipod-sync \
  --predicate-type https://spdx.dev/Document/v2.3
```

Release-specific hashes are published in:

```text
SHA256SUMS
```

rather than being embedded into the tagged source tree.

---

# Architecture

For implementation details, component boundaries, synchronization stages, transaction behavior, and trust boundaries, see:

```text
docs/ARCHITECTURE.md
```

For release construction, verification, publication, rollback, and operational procedures, see:

```text
docs/RELEASE-RUNBOOK.md
```

Keeping those details in dedicated documents avoids duplicating the same low-level material throughout the README.

The README is intended to answer:

> How do I safely install, configure, and use `open-ipod-sync`?

The architecture and release documents answer the deeper implementation and maintainer questions.

---

# Development checks

Before submitting a change, run:

```bash
./tools/public-sanity-check.sh
```

For release-related work, also follow:

```text
docs/RELEASE-RUNBOOK.md
```

Changes affecting synchronization safety should preserve the project's fail-closed transaction model and read-only source guarantees.

---

# License

This repository includes the GNU Lesser General Public License version 2.1 in:

```text
LICENSE
```

Third-party code retains its respective copyright and licensing terms.

See:

```text
THIRD_PARTY.md
```

and the notices included with the corresponding source.

## Source and native-code security hardening

The configured music source remains a strict read-only security boundary.

Source discovery is fail-closed. `ipod-sync` recursively supports ordinary
nested directories, but it refuses filesystem objects that could make source
resolution ambiguous or escape the configured source tree:

- source-root symlinks;
- file symlinks, including links whose targets remain inside the source tree;
- directory symlinks;
- broken symlinks;
- FIFOs;
- Unix sockets;
- device nodes and other non-regular special files.

Every source path component is checked without following symlinks. Tracks are
revalidated again before write authorization, including identity, size, and
SHA-256 checks. A source path that changes into a symlink or otherwise changes
identity during the operation is rejected.

This deliberately uses a stricter policy than merely checking where a symlink
eventually resolves. Ordinary real nested directories remain supported.

Filenames are treated as data rather than shell syntax. Regression tests cover
leading dashes, quotes, shell metacharacters, embedded newlines, Unicode, and
nested paths. External media tools are invoked with argument vectors rather
than shell command interpolation.

Native components are compiled with explicit production hardening, including:

- stack-protector hardening;
- fortified libc calls where supported;
- format-string security checks;
- PIE;
- RELRO;
- immediate symbol binding;
- non-executable stack;
- `-fno-common`.

The packaged `sync-envelope` ELF is checked during both package construction and
package audit. A package fails validation if the required ELF hardening
properties are absent.

CI also builds the project-native C components with AddressSanitizer and
UndefinedBehaviorSanitizer. The CDB signer and Rijndael implementation receive
runtime sanitizer smoke coverage.

`sync-envelope` is sanitizer-built but is intentionally not executed by the
automated sanitizer smoke test because starting it can initiate the real
libimobiledevice sync protocol with a physically connected device. Device
communication is therefore kept outside this automated security test.

<!-- CI_SECURITY_HARDENING_SUMMARY_BEGIN -->
## CI, security, privacy, reproducibility, and release integrity

`open-ipod-sync` treats CI as part of the security model. The pipeline does
much more than compile a Debian package: it verifies source-library safety,
package integrity, privacy boundaries, native-code hardening,
reproducibility, provenance, and release eligibility.

### CI pipeline

The main CI workflow contains the following release-critical jobs.

#### Public source sanity — Python 3.9

This job runs repository-level safety and policy checks, including:

- Python/source validation;
- source-path security tests;
- strict read-only source-library invariants;
- privacy-boundary tests;
- native ELF hardening checks;
- native sanitizer coverage where runtime execution is safe;
- deterministic source-archive tests;
- reproducibility-claim scope tests;
- workflow-security policy checks; and
- checks that CI validation does not leave unexpected source-tree changes.

#### Debian 11 package build + audit

The canonical package build runs in the pinned Debian 11 build environment.

It:

- builds the Debian package;
- audits package layout and metadata;
- verifies runtime dependencies;
- verifies file permissions and executable layout;
- checks configuration-file handling;
- checks native ELF security properties;
- scans package/privacy boundaries;
- generates an SPDX SBOM;
- generates provenance metadata;
- generates the canonical `SHA256SUMS`; and
- uploads only the expected audited CI artifact set.

The audited public CI artifact bundle contains:

- `ipod-sync_*.deb`;
- `ipod-sync_*.spdx.json`;
- `PROVENANCE.json`; and
- `SHA256SUMS`.

Internal reproducibility evidence is not silently added to this public artifact
contract.

#### Debian 11 reproducibility gate

The reproducibility gate independently reconstructs the package from a
deterministic archive of the committed Git object.

It verifies that:

- repeated source-archive generation is byte-for-byte deterministic;
- the archive identifies the expected Git commit;
- the archive contains no `.git` metadata;
- the extracted source contains no `.git` metadata;
- Git execution is disabled during the extracted-source rebuild;
- source timestamps preserve the commit-derived `SOURCE_DATE_EPOCH`;
- comparison builds use different filesystem paths;
- comparison builds use different `HOME` directories;
- comparison builds use different `TMPDIR` directories;
- timezone differences do not affect output;
- locale differences do not affect output;
- Python hash-seed differences do not affect output;
- umask differences do not affect output;
- synthetic user identity differences do not affect output;
- build-parallelism differences do not affect output;
- the actual rebuild runs with socket/network syscalls denied by the kernel;
- the ambient process environment is replaced using `env -i`;
- executable lookup is limited to a declared Debian-owned toolchain;
- developer-local executable paths are excluded;
- both builders record identical toolchain identities;
- both builders record identical build-material identities; and
- the complete supply-chain bundles are byte-for-byte identical.

The byte comparison covers:

- the Debian package;
- SPDX SBOM;
- provenance metadata; and
- `SHA256SUMS`.

The normal checkout build is also compared against the isolated
source-archive build so the hardened reproducibility path cannot silently
produce a different package.

#### Debian 11 package lifecycle

The lifecycle job operates on the already-audited Debian package.

It validates installation and package lifecycle behavior using the intended
runtime dependency environment.

#### Ubuntu host compatibility

Host compatibility is validated on:

- Ubuntu 24.04; and
- Ubuntu 26.04.


The Ubuntu 26.04 compatibility job additionally exercises the `ifuse` safety
boundary. It verifies that the distro-provided 1.2.0 release is rejected,
installs upstream 1.2.1 under `/usr/local`, verifies that the safe binary is
selected by `PATH`, and then runs the package lifecycle against that safe
runtime. Ubuntu 24.04 continues to exercise its distro-provided 1.1.4 line.

This keeps package reproducibility separate from runtime host compatibility.

#### GitHub artifact attestations

GitHub artifact attestations are generated for the audited supply-chain
artifacts.

They provide an independently verifiable link between an artifact and the
GitHub repository/workflow execution that produced it.

---

### Workflow and dependency security

GitHub Actions workflows are treated as privileged code.

The repository includes:

- a dedicated workflow-security policy checker;
- an allowlist of permitted GitHub Actions;
- full commit-SHA pinning for Actions instead of floating tags;
- CODEOWNERS coverage for security-sensitive paths;
- Dependabot configuration;
- CodeQL analysis;
- pull-request dependency review;
- GitHub secret scanning;
- GitHub push protection; and
- a protected release environment with a required reviewer.

Workflow-policy checks run in CI so workflow changes cannot silently introduce
unapproved Actions or weaken the SHA-pinning policy.

---

### Strict read-only source-library security

A fundamental invariant of `open-ipod-sync` is:

> The source music library is read-only.

This applies to local directories and NAS-hosted libraries.

No dry run, apply operation, recovery operation, hashing operation, media
probe, candidate generation, rollback path, state-management operation, or
transcoding workflow may write to the source tree.

Source-path hardening includes:

- rejecting a source root that is itself a symlink;
- no-follow traversal;
- rejecting file symlinks;
- rejecting directory symlinks;
- rejecting internal symlinks;
- rejecting external symlinks;
- rejecting broken symlinks;
- rejecting FIFOs;
- rejecting Unix sockets;
- rejecting block devices;
- rejecting character devices;
- rejecting other unexpected special filesystem nodes;
- supporting ordinary nested source directories;
- deterministic traversal ordering;
- containment validation;
- path-component revalidation;
- file identity revalidation around probing;
- file identity revalidation around hashing; and
- subprocess argument arrays instead of shell interpolation.

The source library is never used for:

- application state;
- caches;
- temporary files;
- generated metadata;
- sidecars;
- transcoded output;
- rollback state; or
- recovery state.

---

### Native-code hardening

Native helpers are built with hardened compiler and linker settings,
including:

- stack-protector hardening;
- `_FORTIFY_SOURCE`;
- PIE;
- RELRO;
- immediate symbol binding;
- non-executable stack enforcement;
- format-security checks;
- reproducible file/debug/macro prefix mapping; and
- strict warning flags.

CI verifies the resulting ELF properties rather than relying only on the
compiler command line.

Native-code coverage also includes ASan and UBSan builds.

Runtime sanitizer execution is limited to code paths that are safe to execute
without entering a real device-sync protocol. The device-sync envelope is
compiled with sanitizer instrumentation but deliberately not executed during
the sanitizer test.

---

### Artifact privacy boundary

Artifacts are scanned before crossing public CI or release boundaries.

The canonical privacy scanner checks ordinary files and supported archives for
sensitive information including:

- private home-directory paths;
- private/RFC1918 network addresses;
- credentials and token-like values;
- private keys;
- Apple device identifiers;
- pairing records;
- legacy device fingerprints; and
- other project-defined private patterns.

The scanner:

- fails closed;
- reports findings in redacted form;
- inspects supported archives; and
- does not follow arbitrary symlinks while traversing inputs.

Privacy scanning is applied to relevant:

- source validation;
- Debian package contents;
- CI bundles;
- reproducibility artifacts;
- source archives; and
- release-boundary artifacts.

Checksum-sidecar generation is also designed to contain relative artifact
names rather than leaking private absolute build paths.

---

### Deterministic committed-source archive

Independent rebuilds do not trust the mutable CI checkout as their source.

CI creates a deterministic tar archive directly from the committed Git object.

Tests verify:

- repeated generation is byte-for-byte identical;
- embedded Git commit identity is correct;
- `.git` metadata is absent;
- required build sources are present;
- commit-derived timestamps are preserved; and
- required executable modes are preserved.

Because the archive comes directly from the committed Git object, dirty or
untracked files cannot silently become rebuild inputs.

---

### Rebuild without Git metadata

The independent comparison build runs from the extracted source archive, not a
Git checkout.

The extracted source contains no `.git` metadata.

A deliberately failing `git` executable is inserted into the isolated build
environment. Any unexpected attempt to invoke Git therefore fails instead of
silently depending on repository metadata.

`SOURCE_DATE_EPOCH` remains deterministic through the source archive timestamp
fallback.

---

### Environment-variance reproducibility

Two independent comparison builders intentionally vary values that commonly
cause accidental non-reproducibility.

The differing inputs include:

- extraction/build path;
- `HOME`;
- `TMPDIR`;
- timezone;
- locale;
- `PYTHONHASHSEED`;
- umask;
- synthetic `USER`;
- synthetic `LOGNAME`; and
- build parallelism.

Despite these differences, both builders must produce byte-identical
supply-chain outputs.

---

### Kernel-enforced network isolation

Dependency acquisition is separated from the actual comparison build.

After the pinned Debian environment has been prepared, the comparison build is
executed through `network-deny-exec`.

Before starting the build it:

- rejects socket-backed standard descriptors;
- closes inherited non-standard file descriptors;
- enables `PR_SET_NO_NEW_PRIVS`; and
- installs a Linux seccomp filter.

The filter denies socket/network syscalls with `EPERM`.

Because seccomp restrictions are inherited by child processes, the protection
also applies to build subprocesses and the metadata-generation process.

Tests explicitly verify that IPv4 socket creation fails under this policy.

This is stronger than simply relying on proxy variables or checking that
`curl` and `wget` are absent from the build script.

---

### Empty inherited build environment

The independent builders use:

```text
env -i
```

Only explicitly selected environment variables are passed to the build.

This prevents unrelated values from the runner, login session, shell,
developer machine, or CI host from silently influencing the independent
rebuild.

---

### Declared Debian-owned toolchain

The comparison build does not inherit the runner's normal `PATH`.

A generated toolchain view exposes only declared commands required by the
build.

Every declared executable:

- must resolve below `/bin`, `/sbin`, `/usr/bin`, or `/usr/sbin`;
- must resolve to a regular executable;
- must be executable;
- must have a Debian package owner;
- records its owning package; and
- records the installed package version.

The policy understands Debian merged-`/usr` aliases. For example,
`/usr/bin/bash` can correctly map to package metadata recorded as `/bin/bash`.

Developer-local executable roots such as:

- `/usr/local`;
- home directories;
- `/opt`; and
- temporary directories

are excluded from command lookup.

Tests inject hostile fake tools into the ambient `PATH` and verify that those
executables do not enter the declared toolchain.

Both independent builders must produce byte-identical toolchain manifests.

---

### Recorded build materials

Each independent builder produces a canonical build-material manifest.

The manifest records:

- source commit;
- `SOURCE_DATE_EPOCH`;
- source-archive SHA-256;
- Debian snapshot identity;
- pinned Debian base-image digest;
- Debian architecture;
- Debian version;
- installed build-package names and versions;
- relevant pkg-config modules and versions; and
- compiler, linker, binutils, packaging, Python, gettext, make, and related
  tool versions.

Both isolated builders must produce byte-identical material manifests before
their output comparison is accepted.

This makes important build inputs inspectable rather than treating the CI
environment as an opaque black box.

---

### Pinned Debian acquisition environment

The Debian build jobs use:

- Debian 11 pinned by container-image digest; and
- package repositories pinned to a dated Debian Snapshot.

The model intentionally separates:

1. **dependency acquisition**
   - the pinned container is obtained;
   - the pinned Debian Snapshot is configured;
   - declared dependencies are installed;

2. **independent comparison build**
   - dependencies are already installed;
   - the deterministic source archive is extracted;
   - networking is kernel-denied;
   - the declared toolchain is used;
   - outputs are compared.

The project therefore does not claim that the entire GitHub Actions job never
uses networking.

Instead, it verifies that the **actual independent rebuild does not require
network access**.

---

### Reproducible supply-chain metadata

Reproducibility applies to the complete audited bundle, not only the `.deb`.

Independent builders generate and compare:

- Debian package;
- SPDX SBOM;
- `PROVENANCE.json`; and
- `SHA256SUMS`.

All must match byte-for-byte.

This also verifies that SBOM and provenance generation is deterministic under
the tested environment variance.

---

### Package audit and configuration management

The Debian package audit validates the finished package rather than trusting
only the commands that produced it.

The audit covers package structure, dependencies, native hardening,
configuration behavior, privacy boundaries, and other package invariants.

Runtime `config.env` is managed by package installation behavior rather than
being treated as an uncontrolled build artifact.

---

### Safe build-time temporary files

Build-time compiler probes use private `mktemp` paths below `TMPDIR` rather
than fixed predictable filenames.

This avoids relying on a shared hard-coded `/tmp` filename and allows the
reproducibility matrix to vary `TMPDIR` safely.

---

### Release integrity

The release process layers multiple independent controls:

1. public source/policy validation;
2. strict source-path safety;
3. package build and audit;
4. privacy scanning;
5. deterministic committed-source reconstruction;
6. independent environment-variance rebuilding;
7. kernel-enforced network isolation;
8. declared Debian-owned tool resolution;
9. recorded build-material identities;
10. byte-for-byte supply-chain bundle comparison;
11. package lifecycle validation;
12. supported-host compatibility;
13. release workflow gating;
14. cryptographic checksums;
15. SBOM and provenance metadata; and
16. GitHub artifact attestations.

These controls make release artifacts substantially easier to inspect,
reproduce, and independently verify.

---

### Scope of the build-isolation guarantee

The verified property is a:

**reproducible, network-isolated, material-recorded,
tool-resolution-confined build.**

The current reproducibility environment does **not** claim a complete
filesystem sandbox.

Comparison-build processes can still:

- read operating-system files supplied by the pinned Debian environment; and
- execute an explicitly named absolute system executable if build logic
  deliberately requests it.

System headers, shared libraries, and operating-system files are trusted
through:

- the pinned Debian image digest;
- the pinned Debian Snapshot;
- installed package identities and versions;
- recorded pkg-config identities;
- recorded tool identities; and
- byte-for-byte output comparison.

They are not individually content-addressed at every filesystem read.

Landlock is not required by the Debian 11 baseline because the supported Linux
5.10 environment does not expose the required Landlock interface.

Keeping this boundary explicit prevents CI documentation from claiming a
stronger filesystem-isolation property than the project actually verifies.
<!-- CI_SECURITY_HARDENING_SUMMARY_END -->

<!-- CONSUMER_RELEASE_VERIFICATION_BEGIN -->
## Independently verify a release

Every new release publishes enough evidence for a consumer to verify the
downloaded package without access to the original GitHub Actions workspace,
an iPod, or the user's music library.

A release contains exactly these eight assets:

```text
CI-SHA256SUMS
PROVENANCE.json
SHA256SUMS
BUILD-MATERIALS.json
TOOLCHAIN.json
open-ipod-sync-<40-character-commit>-source.tar
ipod-sync_<public-version>_amd64.deb
ipod-sync_<public-version>_amd64.spdx.json
```

`SHA256SUMS` covers the other seven public release assets.
`CI-SHA256SUMS` preserves the identities of the six payloads produced by the
audited Debian 11 CI build before the Debian package and SPDX filenames are
normalized for GitHub Release publication.

The deterministic source archive is generated from the exact release commit.
`BUILD-MATERIALS.json` records the source archive digest, source commit,
`SOURCE_DATE_EPOCH`, declared Debian snapshot/base-image identities, and
observed build packages/tools. `TOOLCHAIN.json` records the Debian-owned
commands admitted to the reproducibility build and the tool-resolution policy.

### Requirements for local verification

For the offline verification mode you need:

```text
python3
dpkg-deb
```

On Debian or Ubuntu, `dpkg-deb` is provided by the `dpkg` package.

For GitHub authenticity verification you additionally need the GitHub CLI:

```text
gh
```

If required by your GitHub CLI configuration, authenticate first:

```bash
gh auth login
```

### 1. Download the release assets

From a checkout of this repository, choose the release tag and download all
assets into an otherwise empty directory:

```bash
REPO="pssingh21/open-ipod-sync"
TAG="v0.2.0-alpha.7"
RELEASE_DIR="$PWD/release-verify-$TAG"

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

gh release download "$TAG" \
  --repo "$REPO" \
  --dir "$RELEASE_DIR"
```

For a future release, replace `TAG` with that release's tag.

### 2. Verify the downloaded bytes offline

The core verifier does not contact GitHub or any other network service:

```bash
python3 tools/verify-release.py \
  "$RELEASE_DIR" \
  --expected-repository \
  "https://github.com/$REPO"
```

To pin verification to an already-known commit, also provide:

```bash
python3 tools/verify-release.py \
  "$RELEASE_DIR" \
  --expected-commit "<40-character-commit>" \
  --expected-repository \
  "https://github.com/$REPO"
```

The offline verifier fails closed unless all of the following agree:

- the directory contains exactly the eight expected release assets;
- `SHA256SUMS` contains exactly the seven expected payload entries and every
  digest matches;
- `CI-SHA256SUMS` contains exactly the six audited CI payload identities;
- the source archive filename, embedded Git commit, canonical root prefix, and
  timestamps agree with `BUILD-MATERIALS.json`;
- the source archive SHA-256 matches the digest recorded in
  `BUILD-MATERIALS.json`;
- the build-material schema and declared/observed environment records are
  structurally valid;
- the declared toolchain has no ambient `PATH` dependency, does not permit
  developer-local roots, and its command targets remain inside the declared
  executable roots;
- `PROVENANCE.json` identifies the exact package digest, source commit,
  `SOURCE_DATE_EPOCH`, Debian snapshot, package metadata, and SPDX digest;
- the package files recorded in provenance hash to the exact bytes extracted
  from the released `.deb`;
- the SPDX document describes the released package and binds the package
  SHA-256 and source commit.

This verification is independent of the original CI workspace. It does not
expand the documented build-isolation scope; the separately documented PR 4
filesystem-read boundary still applies.

### 3. Verify GitHub release authenticity

After the offline checks pass, the optional online mode verifies the GitHub
publication and attestations as well:

```bash
python3 tools/verify-release.py \
  "$RELEASE_DIR" \
  --expected-repository \
  "https://github.com/$REPO" \
  --github \
  --repo "$REPO" \
  --tag "$TAG"
```

The GitHub authenticity layer additionally requires:

- the GitHub Release to be immutable and non-draft;
- the remote release asset set to exactly match the eight locally verified
  files;
- the release tag to resolve to the same source commit encoded by the source
  archive and build materials;
- GitHub release verification to succeed for the release and every asset;
- the CI-originating package, SPDX document, provenance, CI checksum manifest,
  source archive, build-material manifest, and toolchain manifest to have valid
  GitHub artifact attestations;
- attestations to identify this repository's `.github/workflows/ci.yml`,
  the verified source commit, `refs/heads/main`, and a non-self-hosted runner;
- the Debian package to have the expected SPDX attestation.

GitHub verification is deliberately opt-in. Running `verify-release.py` without
`--github` remains an offline operation.

### What independent verification proves

A successful verification establishes a chain from the downloaded Debian
package back to the exact published source commit and the build evidence
recorded by CI:

```text
GitHub release/tag
        |
        v
exact eight-asset release set
        |
        +--> SHA256SUMS
        |
        +--> deterministic source archive
        |        |
        |        +--> exact Git commit
        |        +--> BUILD-MATERIALS.json
        |
        +--> TOOLCHAIN.json
        |
        +--> PROVENANCE.json
        |        |
        |        +--> Debian package SHA-256
        |        +--> source commit / SOURCE_DATE_EPOCH
        |        +--> SPDX SHA-256
        |
        +--> SPDX document
        |
        `--> Debian package
```

The verification path never reads or modifies the music source directory and
never requires an iPod. The source-library read-only invariant remains
unchanged.
<!-- CONSUMER_RELEASE_VERIFICATION_END -->

<!-- PR4_BUILD_ISOLATION_SCOPE_BEGIN -->
### Build isolation scope

The Debian 11 reproducibility gate verifies more than a second package build.
It reconstructs the package from a deterministic archive of the committed Git
object and validates the following properties:

- the source archive is byte-reproducible and contains no `.git` metadata;
- the extracted rebuild cannot invoke Git;
- independent builders use different build paths, `HOME`, `TMPDIR`, timezone,
  locale, Python hash seed, umask, synthetic user identity, and make
  parallelism;
- the actual rebuild and metadata-generation processes run with socket/network
  syscalls denied by a Linux seccomp filter;
- inherited non-standard file descriptors are closed and socket-backed standard
  descriptors are refused before the isolated process is started;
- the ambient process environment is replaced with `env -i`;
- executable lookup is restricted to an explicit toolchain view;
- every executable in that view resolves to a Debian-package-owned system tool,
  excluding developer-local paths such as `/usr/local`, home directories,
  `/opt`, and temporary directories;
- the source archive digest, Debian snapshot identity, pinned base-image
  identity, build-package versions, pkg-config module versions, and important
  tool versions are recorded as build materials;
- the two isolated builders must report byte-identical build-material and
  toolchain manifests; and
- the resulting Debian package, SPDX SBOM, provenance, and checksum manifest
  must be byte-for-byte identical.

This is intentionally a narrower guarantee than a complete filesystem sandbox.
The build can still read operating-system files outside the extracted source
tree and can execute an absolute system path if build logic explicitly names
one. System headers and libraries are therefore trusted through the pinned
Debian base image, snapshot, installed package set, and recorded material
identities rather than through per-file read-time content addressing.

The project describes this property as a **reproducible, network-isolated,
material-recorded, tool-resolution-confined build**. The current Debian 11
baseline does not require Landlock or another filesystem-read sandbox, which
keeps the reproducibility gate usable on the supported Linux 5.10 environment.
<!-- PR4_BUILD_ISOLATION_SCOPE_END -->

<!-- REPOSITORY_POLICY_BEGIN -->
## Repository security and release policy

GitHub-side branch protection, required checks, Actions permissions, security
controls, release-environment protection, immutable releases, and version-tag
protection are documented in
[`docs/REPOSITORY-POLICY.md`](docs/REPOSITORY-POLICY.md).

Maintainers can verify the live GitHub configuration without modifying it:

```bash
python3 tools/audit-repository-policy.py
```

The repository-policy audit is independent of synchronization data and never
accesses or modifies the configured music source, NAS content, or iPod.
<!-- REPOSITORY_POLICY_END -->
