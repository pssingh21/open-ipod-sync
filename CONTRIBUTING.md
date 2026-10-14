# Contributing

Contributions are welcome, especially testing on additional legacy Apple devices
and Linux distributions.

## Before submitting a change

Run:

```bash
./tools/public-sanity-check.sh
```

It must pass.

For changes affecting packaging, also rebuild the Debian package and inspect the
generated package before submitting the change.

## Safety requirements

Changes must preserve the project's fail-closed behavior.

In particular:

- music sources must never be modified;
- source write-barrier failures must stop execution;
- normal iPod access should remain read-only;
- device writes must require explicit authorization;
- failed transactions must not silently commit partial database state;
- existing tracks must not be deleted or modified by the ADD-only path.

## Device testing

When reporting device-test results, include:

- iPod/iPhone model;
- OS version;
- Linux distribution and version;
- CPU architecture;
- command executed;
- whether the operation was read-only or a live transaction.

Do not include device identifiers, pairing records, credentials, private file
paths, private IP addresses, or personal media.

## Scope

Please keep unrelated modernization and formatting changes separate from
device-write behavior changes so that synchronization logic remains reviewable.
