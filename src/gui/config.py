from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths


APP_NAME = "smartswitch-explorer"


def _config_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    if not base:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.ConfigLocation)
    if not base:
        base = str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path() -> Path:
    return _config_dir() / "settings.json"


def _legacy_settings_path() -> Path | None:
    legacy_base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if not legacy_base:
        return None
    legacy = Path(legacy_base) / "settings.json"
    if legacy == _settings_path():
        return None
    return legacy


def default_destination() -> Path:
    documents = Path.home() / "Documents"
    dest = documents / "SmartSwitch Extracted Backups"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def load_settings() -> dict:
    path = _settings_path()
    if not path.exists():
        legacy_path = _legacy_settings_path()
        if legacy_path and legacy_path.exists():
            path = legacy_path
        else:
            return {
                "destination": str(default_destination()),
                "last_backup": "",
            }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {
        "destination": data.get("destination") or str(default_destination()),
        "last_backup": data.get("last_backup") or "",
    }


def save_settings(settings: dict) -> None:
    path = _settings_path()
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
