# Security Policy

`ipod-sync` interacts with legacy Apple devices and performs low-level media
database operations. Bugs may cause library corruption or unintended device
changes.

## Reporting a vulnerability

Do not post credentials, pairing records, device identifiers, private media,
private filesystem paths, or other sensitive information in a public issue.

If GitHub private vulnerability reporting is available for this repository,
please use it for security-sensitive reports.

Otherwise, open a minimal public issue stating that you have a security report
without including sensitive details.

## Safety-sensitive areas

Reports are particularly useful for issues involving:

- unintended writes to the configured source filesystem;
- device writes without explicit authorization;
- path traversal;
- unsafe temporary-file handling;
- command injection;
- malformed or hostile media metadata;
- database corruption;
- rollback/recovery failures;
- leakage of device-specific signing material or identifiers.

## Supported versions

During the alpha stage, only the latest published alpha receives security fixes.
