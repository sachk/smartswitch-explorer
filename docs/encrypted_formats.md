# Encrypted Format Coverage

This project now centralizes Smart Switch decryption in `lib/smartswitch_core/crypto/smartdecrypt.py`.

## Implemented decoder

- `AES-CBC` with:
  - IV in first 16 bytes of the payload
  - key derived via Smart Switch dummy key hash (`derive_dummy_key`)
  - trailing non-block bytes ignored when present

This decoder is used for:

- message `.bk` payloads
- call log `.exml` payloads in `CALLLOG/CALLLOG.zip`
- many encrypted members in other category zip archives (`.enc`, `.exml`, `*Encrypted*`, `enc_*`)
- Galaxy Watch `*encp` files in `GALAXYWATCH_CURRENT`/`GALAXYWATCH_BACKUP`

### Password/PIN compatibility

When a backup password is entered in Export Options, the shared decoder also tries the
Smart Switch 4.1.16 PIN-based layouts documented by Park, Kim, and Kim:

- `MK = PBKDF2-HMAC-SHA1(password, legacy dummy/DK, 1000, 32)`
- equation 5: `AES-128-CBC` with `SHA-256(MK)[0:16]` and a prefixed IV
- equation 6: `AES-256-CBC` with
  `PBKDF2-HMAC-SHA1(MK, prefixed salt, 1000, 32)`, a prefixed IV, and a prefixed salt

The direct dummy-key derivation remains a candidate for newer formats. The password is passed
to message, call-log, application, settings, storage, and other-category exports. This gives
Secure Folder backup categories the same generic encrypted-member recovery path while always
preserving their raw files.

These PIN-derived compatibility paths are covered with generated fixtures but have not yet
been verified against a real password-protected Smart Switch backup. Smart Switch versions and
devices may use a different DK or wrapping format; in that case the raw export remains intact.

### RCS message databases

`RcsMessage.edb` is an AES-CBC encrypted ZIP containing `mmssms.db`. JSON exports now contain
the `im` and `ft` tables; CSV exports write `rcs_im.csv` and `rcs_ft.csv`. Native mode preserves
the encrypted EDB unchanged.

### Legacy call logs

Call-log conversion accepts the normal prefixed-IV layout, the older fixed-IV layout, and
plaintext XML. Illegal XML 1.0 control bytes are removed before parsing so a malformed contact
field does not prevent the remaining call log from being exported.

## Application backup payloads

### Partial APK encryption (`APKFILE/*.penc`)

Smart Switch Mobile 3.7.71.16 uses this layout:

- 4-byte big-endian encrypted-segment length (at most `0x100010`)
- an AES-CBC/PKCS#5 encrypted prefix
  - fixed IV `26c7d1d26c142de0a3b82f7e8f90860a`
  - 128-bit key: first 16 bytes of SHA-256 over the backup dummy string
- the remainder of the APK ZIP stored unchanged

When the dummy key is unavailable, the ZIP central directory and entries wholly beyond the
encrypted prefix remain recoverable. The exporter writes those entries to
`apk_recovered_files`; entries overlapping the prefix fail their ZIP integrity checks.

For external-storage backups, Smart Switch reads `Dummy` from `SmartSwitchBackup.json`. A
64-character hexadecimal value is decoded to a UTF-8 string before key derivation. PC backups
can instead use a device/session dummy supplied during backup. Constants embedded in the APK
implement legacy defaults and key derivation; they do not reproduce a randomly supplied dummy.

### Android application data (`APKFILE/*.data`)

`APKFILE/<package>.data` files use the Android Backup stream format when they
start with `ANDROID BACKUP`.

The implemented decoder validates the encrypted Android Backup header before
extracting:

- backup version, compressed flag, and encryption algorithm
- salt, IV, and ciphertext lengths
- AES-CBC/PKCS#7 padding for the encrypted master-key blob
- the complete master-key blob structure: master IV, master key, and checksum
- PBKDF2-HMAC-SHA1 master-key checksum
- AES-CBC/PKCS#7 padding for the payload
- zlib decompression when the header says the stream is compressed
- TAR structure and safe TAR member names/types

For Smart Switch for Windows backups, the session `Dummy` is recovered from
`backupHistoryInfo.xml`. Smart Switch stores that value as hexadecimal
AES-128-ECB ciphertext with zero padding. For basic (`LEVEL_1`) backups, the
recovered value is the password passed to the Android backup service. The old
project constant remains a last compatibility candidate, but it is a value from
another session rather than a universal Smart Switch credential.

A candidate credential is accepted only if the master-key checksum validates
and the decrypted result is a valid TAR stream. A malformed or absent metadata
file therefore cannot turn random plaintext into accepted output.

If a real `.data` file has a valid Android Backup header but cannot unwrap the
master key with the available credential, the app reports:

```text
Unable to unwrap the master key with the available credential.
The backup may require a different Smart Switch session key or password.
```

This means the file is encrypted with a credential the project does not have. It
does not by itself imply corruption. PIN-protected backup credential derivation
is not currently exposed by the application.

Non-sensitive diagnostics can be collected without printing passwords, keys,
salts, IVs, decrypted content, or TAR member names:

```bash
uv run python scripts/diagnose_data_file.py --try-empty /path/to/APKFILE/package.data
```

When the input is directly inside `APKFILE`, the script automatically checks the
sibling `backupHistoryInfo.xml`. A different root can be supplied with
`--backup-dir`.

For an optional local real-file test:

```bash
SMARTSWITCH_REAL_DATA=/path/to/APKFILE/package.data uv run pytest -m real_backup -v
```

That optional test now requires authenticated decryption and a valid TAR. It no
longer passes merely because a missing credential was diagnosed correctly.

## Application `.penc` payloads

`APKFILE/<package>.penc` uses a four-byte framing header followed by an
AES-128-CBC/PKCS#7 encrypted prefix. Smart Switch encrypts at most the first
1 MiB of the APK and leaves the remainder unchanged. The key is the first 16
bytes of `SHA-256(session Dummy)` and the IV is fixed by the format.

The decoder only accepts the result after all of these checks pass:

- ZIP magic and central directory
- CRC for every ZIP member
- root `AndroidManifest.xml`
- base `classes.dex`

This behavior was cross-checked against the Smart Switch packet/proof-of-concept
implementation in `bugscale/samsung-s25-research` and the credential workflow
published in *Forensic Science International: Digital Investigation*, DOI
`10.1016/j.fsidi.2021.301310`.

## Galaxy Watch notes

- `GALAXYWATCH_*_FileEncryptionInfo.json` is used to map encrypted file names to original logical paths.
- Decrypted watch outputs are written under:
  - `galaxy_watch/<current|backup>/decoded/...`

## Unknown/partial cases

- Some decrypted payloads remain binary/unknown (for example `AppList.bk`-style watch blobs), even after first-layer decryption.
- Those are still exported as decrypted binary files for offline analysis.
- In the current sample backup, binary/partially-decoded examples include:
  - `APKFILE/AppList.bk`
  - `GALAXYWATCH_CURRENT/*AppListbkencp`
  - `SHEALTH2/.../encryptedKeystore`
  - `DISPLAYMANAGER/.../backup_encrypt_brightness.xml`

## Newer message backup layout: `GMMESSAGE` (observed 2026-02-22 sample)

In backup `SM-F956B_20260222185452`, messages are no longer under `MESSAGE/`.
The backup uses:

- `GMMESSAGE/d2d_item_info.json`
- `GMMESSAGE/item_instant_*_size_*_id_*` payload files

PoC decoder script:

- `scripts/poc_decode_gmmessage.py`

Run:

```bash
python scripts/poc_decode_gmmessage.py ~/Documents/SmartSwitchBackups/SM-F956B_20260222185452
```

PoC output for this sample:

- output file: `~/Documents/SmartSwitchBackups/analysis/SM-F956B_20260222185452_gmmessage_poc.json`
- metadata entries: `1284`
- payload files present: `1283`
- missing referenced payload: `1` (`item_instant_1771746893432_size_9977856_id_0`)
- metadata `c` field (Base64 protobuf) parse errors: `0`
- observed payload types: `jpeg=663`, `png=499`, `pdf=53`, `mp4=49`, `gif=13`, `vcard=5`, `webm=1`

Current interpretation:

- `GMMESSAGE` appears to be a message-media backup set with protobuf metadata in `d2d_item_info.json`.
- The PoC currently decodes metadata structure and joins it with payload file facts (existence, size, inferred type).
- Full semantic decoding of protobuf fields is not yet implemented.

Entropy check for encryption likelihood (same sample):

- report file: `~/Documents/SmartSwitchBackups/analysis/SM-F956B_20260222185452_entropy_report.json`
- payload file entropy median: `7.964` (high, but expected for compressed media)
- payload magic signatures covered all files: `jpeg=663`, `png=499`, `pdf=53`, `mp4=49`, `gif=13`, `vcard=5`, `webm=1`, `unknown=0`
- metadata `c` blobs entropy median: `4.888` (protobuf-like structure, not ciphertext-like)

Interpretation:

- high entropy here is explained by known media/document formats, not by opaque encrypted containers
- no evidence of an additional encrypted message payload among present `GMMESSAGE/item_instant_*` files
- the only likely message-text container remains the missing `item_instant_1771746893432_size_9977856_id_0` file
