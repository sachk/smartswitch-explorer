# SmartSwitch Explorer

SmartSwitch Explorer is a desktop app for finding encrpyted Samsung Smart Switch backups and exporting the decrypted contents:

- Messages (CSV or JSON)
- Applications (extracted data + APKs)
- Photos and videos
- Contacts
- Call log
- Galaxy Watch backups
- Storage, settings, and other backup categories

## Running from source

```bash
uv sync
uv run smartswitch-explorer
```

### Nix:

```bash
nix run github:sachk/smartswitch-explorer
```

## How to use

1. Launch the app.
2. Pick a folder that contains backups, or a parent folder like a mounted home directory, `Documents`, or `Samsung`.
3. Select a detected backup.
4. Choose what to export.
5. Set the destination folder and click **Export Selected**.

Additional format docs:

- `docs/calllog_format.md`
- `docs/encrypted_formats.md`
