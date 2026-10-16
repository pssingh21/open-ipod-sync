# Third-party components

This project interoperates with and/or redistributes pieces from established free-software projects.

- **libgpod 0.8.3**: the release package contains a library rebuilt from the captured modified source; the public source archive includes that corresponding source tree and a reviewable delta. Preserve its upstream/Debian copyright and license notices.
  The bundled delta also corrects `playcounts_plist_read()` GArray element handling: PlayCounts entries are inline `GValue` objects and are addressed as such rather than interpreted as `GValue *` pointers, preventing a parser crash on non-empty `PlayCounts.plist` data.

- **libimobiledevice**: system-provided shared-library dependency.
- **ifuse 1.2.1**: pinned upstream source captured under
  `third_party/ifuse-1.2.1-source/` from
  `libimobiledevice/ifuse`, commit
  `f7eac74184ff240c8ba9cf9b413eed75968a462a`.
  The source includes its upstream LGPL-2.1 license.
  `third_party/ifuse-1.2.1-UPSTREAM.txt` records the source identity.
  This source is being prepared for a private executable in the
  Ubuntu 26.04 package; packaging integration is a separate step.
  `ifuse` 1.2.0 is explicitly unsupported because upstream confirmed a serious data-corruption bug. The fix is available in upstream ifuse 1.2.1.

  The known-unsafe system `ifuse` 1.2.0 remains prohibited for mounting.
- **FFmpeg**: system dependency for audio probing/transcoding; not vendored.

`native/sign-cdb.c` implements legacy Hash72-compatible signing behavior and derives device-specific signing material from the current device's own `HashInfo` and live Apple-signed CDB. No captured device RND/IV/signature is shipped.

This is an engineering notice, not legal advice.
