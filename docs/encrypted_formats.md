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
