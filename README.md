# SmartSwitch Explorer

Native desktop app (PySide6 + Qt widgets) for exploring Samsung Smart Switch backups.

## Scope (v1)

- Messages
- Applications

## Key behavior

- Inventory is built from filesystem structure only.
- No decode/decrypt runs before a user action.
- Metadata enrichment (pretty app names/icons, backup labels) is optional and async.
- Tree sections are collapsed by default.

## Layout

- `src/webapp`: GUI app code.
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

## Tests

```bash
uv run pytest
```

## Export output

Exports are written to:

`<destination>/<backup_id>/...`

Default destination:

`~/Documents/SmartSwitch Extracted Backups`
