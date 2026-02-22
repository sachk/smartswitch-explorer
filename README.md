<h1 align="center">SmartSwitch Explorer</h1>
<p align="center">Desktop app for decrypting Samsung SmartSwitch backups and extracting their contents.</p>

<h3 align="center">
  <a href="https://github.com/sachk/smartswitch-explorer/releases/latest/download/smartswitch-explorer-windows-x64.exe"><strong>Windows (.exe)</strong></a>
  ·
  <a href="https://github.com/sachk/smartswitch-explorer/releases/latest/download/smartswitch-explorer-macos-universal2.dmg"><strong>Mac OS (.dmg)</strong></a>
  <br>
  <a href="https://github.com/sachk/smartswitch-explorer/releases/latest/download/smartswitch-explorer-linux-x86_64.AppImage"><strong>Linux (x64 AppImage)</strong></a>
  ·
  <a href="https://github.com/sachk/smartswitch-explorer/releases/latest/download/smartswitch-explorer-linux-aarch64.AppImage"><strong>Linux (aarch64 AppImage)</strong></a>
  ·
  <a href="https://github.com/sachk/smartswitch-explorer/releases/latest"><strong>Other Downloads</strong></a>
</h3>

SmartSwitch Explorer is a desktop app for finding encrypted Samsung Smart Switch backups and exporting decrypted contents:

- Messages (CSV or JSON)
- Applications (extracted data + APKs)
- Photos and videos
- Contacts
- Call log
- Galaxy Watch backups
- Storage, settings, and other backup categories

## How to use

1. Launch the app.
2. Pick a folder that contains backups, or a parent folder like a mounted home directory, `Documents`, or `Samsung`.
3. Select a detected backup.
4. Choose what to export.
5. Set the destination folder and click **Export Selected**.

## Running from source

```bash
uv sync
uv run smartswitch-explorer
```

### Nix:

```bash
nix run github:sachk/smartswitch-explorer
```

Additional format docs:

- `docs/calllog_format.md`
- `docs/encrypted_formats.md`
