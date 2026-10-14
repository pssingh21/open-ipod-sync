# Third-party components

This project interoperates with and/or redistributes pieces from established free-software projects.

- **libgpod 0.8.3**: the release package contains a library rebuilt from the captured modified source; the public source archive includes that corresponding source tree and a reviewable delta. Preserve its upstream/Debian copyright and license notices.
- **libimobiledevice / ifuse**: system dependencies; not vendored.
- **FFmpeg**: system dependency for audio probing/transcoding; not vendored.

`native/sign-cdb.c` implements legacy Hash72-compatible signing behavior and derives device-specific signing material from the current device's own `HashInfo` and live Apple-signed CDB. No captured device RND/IV/signature is shipped.

This is an engineering notice, not legal advice.
