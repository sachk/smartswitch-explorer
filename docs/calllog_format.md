# Smart Switch Call Log Format

`CALLLOG/CALLLOG.zip` stores encrypted call log XML in a `.exml` entry (for example `/call_log.exml`).

## Payload layout

1. First 16 bytes: AES CBC IV.
2. Remaining bytes: ciphertext encrypted with the Smart Switch dummy-derived AES key.
3. Ciphertext is block-aligned (`16` bytes). Ignore trailing non-aligned bytes if present.

## Decryption flow

1. Derive key with the same logic used for messages (`derive_dummy_key`).
2. Decrypt using `AES-CBC` with the IV prefix.
3. Locate XML start (`<?xml` or `<CallLogs`), then trim trailing null bytes.
4. Parse `<CallLog>` entries and export rows to CSV.

This project implements the logic in `lib/smartswitch_core/additional_export.py`.
