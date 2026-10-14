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
