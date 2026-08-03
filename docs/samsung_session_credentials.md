# Samsung application backup session credentials

## Scope

This note documents the credential flow verified against a Smart Switch for
Windows backup created by Smart Switch PC `4.3.24094_1` and Smart Switch Mobile
`3.7.71.16`. The backup reports `SecurityLevel: LEVEL_1`.

No credential, decrypted application content, or personal metadata is included
here. The real fixture remains outside Git.

## Verified flow

```text
Smart Switch Mobile
  SecureRandom(18 bytes) -> hexadecimal Dummy (36 chars)
          |
          +-> protocol command 0x101, JSON field DUMMY -> Smart Switch PC
          |       |
          |       +-> AES-128-ECB + zero padding -> backupHistoryInfo.xml/Dummy
          |
          +-> getDummy(APKFILE, "APPDATA")
          |       |
          |       +-> BackupManager.fullBackupEx(..., password=Dummy, ...)
          |               -> ANDROID BACKUP v5 .data
          |
          +-> SHA-256(Dummy UTF-8)[0:16] + fixed IV
                  -> AES-CBC/PKCS#7 of first 1 MiB -> .penc
```

The `.data` candidate is not accepted on padding alone. The decoder requires a
valid master-key structure and checksum, valid payload padding, optional zlib
decompression, and a structurally valid TAR.

The `.penc` candidate is accepted only after ZIP parsing, all member CRC checks,
and the presence of `AndroidManifest.xml` and `classes.dex`.

## Evidence

- The real `backupHistoryInfo.xml` contains one 48-byte, AES-aligned encrypted
  `Dummy`. Windows metadata decryption yields a 36-character hexadecimal value.
- That value authenticates the `.data` master-key checksum and produces a
  non-empty valid TAR. The former project default does not authenticate it.
- The same value reconstructs the matching `.penc` into a ZIP whose CRCs all
  pass and which contains a manifest plus one or more DEX files. The former
  project default does not produce ZIP magic.
- Static analysis of Smart Switch Mobile shows `buildMyDevice()` allocating 18
  bytes, filling them with `SecureRandom.nextBytes()`, converting them to hex,
  and assigning the result to the device `Dummy` field.
- The mobile protocol sends that field as `DUMMY` in command `0x101`, named
  `SendDummyValueToPC` in the command enum.
- The application-data producer calls `getDummy(APKFILE, "APPDATA")`, passes the
  result through the APK backup path, and ultimately supplies it as the password
  argument to Samsung's hidden `BackupManager.fullBackupEx` API.
- `bugscale/samsung-s25-research` independently implements `.penc` creation by
  hashing the captured Dummy, taking the first 16 key bytes, and encrypting only
  the first 1 MiB with the fixed IV.

The `if b'"Dummy":"'` check in that research repository is a passive capture
hook: it reads a value from a protocol packet and does not generate one. The
published packet set at the inspected revision does not itself contain a
top-level `Dummy`, so that code is not evidence for a universal value.

## Compatibility and unknowns

- The old `DEFAULT_DUMMY_HEX` remains a fallback for previously supported
  samples, but must not be described as universal.
- The Windows metadata wrapping observed here is implemented. The different
  macOS metadata wrapping described in the literature is not yet implemented.
- Literature reports an additional PIN-based PBKDF2 derivation for protected
  backups. It was not exercised by this `LEVEL_1` sample and is not exposed by
  the application.
- One unique backup session was available. Credential scope across applications,
  sessions, devices, and newer protected-backup modes still needs controlled
  comparison.

## References

- `bugscale/samsung-s25-research`, inspected revision
  `43455a9940fdf5171a3e7eb4c6a8674dc87b0c92`
- Shin et al., "Methods for decrypting the data encrypted by the latest Samsung
  smartphone backup programs in Windows and macOS",
  DOI `10.1016/j.fsidi.2021.301310`
