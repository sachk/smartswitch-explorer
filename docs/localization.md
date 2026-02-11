# Localization

This app uses Qt translation catalogs (`QTranslator`) with source strings defined in Python UI code.

## Current status

- i18n runtime is enabled in `src/gui/localization.py`.
- English catalog source is in:
  - `src/gui/translations/smartswitch_explorer_en.ts`
- If no compiled `.qm` file is present, the app falls back to source strings.

## Add a new locale

1. Create/update a `.ts` file under `src/gui/translations/`:
   - `smartswitch_explorer_<locale>.ts`
2. Compile with Qt Linguist tools (`lrelease`) to produce `.qm`.
3. Place resulting `.qm` in the same folder.
4. On startup, `setup_localization()` attempts:
   - full system locale (e.g. `en_AU`)
   - language short code (e.g. `en`)
   - English fallback (`en`)
