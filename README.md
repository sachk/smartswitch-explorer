# SmartSwitch Explorer

Native desktop app (PySide6 + Qt widgets) for exploring Samsung Smart Switch backups.

## Scope (v1)

- Messages
- Applications
- Photos and videos
- Galaxy Watch backups
- Contacts
- Call log
- Other backup categories (raw copy + zip extraction when present)
- Encrypted Smart Switch artifacts (shared IV-prefix AES decoder)

## Key behavior

- Inventory is built from filesystem structure only.
- No decode/decrypt runs before a user action.
- Metadata enrichment (pretty app names/icons, backup labels) is optional and async.
- Tree sections are collapsed by default.

## Layout

- `src/gui`: GUI app code.
- `lib/smartswitch_core`: reusable scanning/decode/extract libraries.

## Setup

```bash
uv sync
```

If your environment blocks network access, dependency installation may fail.

## Run

```bash
uv run smartswitch-explorer
```

## NixOS Dev Shell

```bash
nix develop
```

The flake dev shell initializes `.venv`, runs `uv sync`, and exports `LD_LIBRARY_PATH`
with `libGL` and required Qt/X11 runtime libraries for PySide6.

## Run via Nix

```bash
nix run
```

This directly runs `uv run smartswitch-explorer` with the same runtime library setup.

## Tests

```bash
uv run pytest
```

## Export output

Exports are written to:

`<destination>/<backup_id>/...`

Default destination:

`~/Documents/SmartSwitch Extracted Backups`

## Format notes

- Call log decryption details: `docs/calllog_format.md`
- Encrypted format coverage: `docs/encrypted_formats.md`
