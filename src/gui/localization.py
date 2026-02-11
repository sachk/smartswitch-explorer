from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator
from PySide6.QtWidgets import QApplication


def tr(context: str, text: str) -> str:
    return QCoreApplication.translate(context, text)


def translations_dir() -> Path:
    return Path(__file__).resolve().parent / "translations"


def _candidate_locale_codes(requested: str | None) -> list[str]:
    code = (requested or QLocale.system().name()).strip()
    if not code:
        return ["en"]
    short = code.split("_", 1)[0]
    out = [code]
    if short != code:
        out.append(short)
    if "en" not in out:
        out.append("en")
    return out


def setup_localization(app: QApplication, locale_code: str | None = None) -> str:
    folder = translations_dir()
    for code in _candidate_locale_codes(locale_code):
        qm_path = folder / f"smartswitch_explorer_{code}.qm"
        if not qm_path.exists():
            continue
        translator = QTranslator(app)
        if translator.load(str(qm_path)):
            app.installTranslator(translator)
            # Keep a strong reference to avoid garbage collection.
            app.setProperty("_app_translator", translator)
            return code
    return "en"


def translate_tree_header(text: str) -> str:
    return tr("TreeModel", text)


def translate_tree_label(kind: str, label: str) -> str:
    by_kind = {
        "messages_root": tr("Inventory", "Messages"),
        "applications_data_root": tr("Inventory", "Application Data"),
        "applications_apk_root": tr("Inventory", "Application APKs"),
        "media_root": tr("Inventory", "Media"),
        "media_photos": tr("Inventory", "Photos"),
        "media_videos": tr("Inventory", "Videos"),
        "watch_root": tr("Inventory", "Galaxy Watch Backups"),
        "watch_current": tr("Inventory", "Current Watch Backup"),
        "watch_backup": tr("Inventory", "Older Watch Backup"),
        "contacts": tr("Inventory", "Contacts"),
        "calllog": tr("Inventory", "Call Log"),
        "storage_root": tr("Inventory", "Storage"),
        "settings_root": tr("Inventory", "Settings"),
        "other_root": tr("Inventory", "Other Backup Data"),
    }
    if kind in by_kind:
        return by_kind[kind]

    by_label = {
        "SMS": tr("Inventory", "SMS"),
        "MMS": tr("Inventory", "MMS"),
        "Attachments": tr("Inventory", "Attachments"),
        "RCS": tr("Inventory", "RCS"),
    }
    return by_label.get(label, label)
