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
